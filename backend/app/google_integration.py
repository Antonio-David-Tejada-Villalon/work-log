"""Integración con Google Calendar (eventos y recordatorios) y Google Tasks (tareas)."""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session

from . import calc
from .db import GoogleToken, get_settings

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]


def configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def _flow(state: Optional[str] = None):
    from google_auth_oauthlib.flow import Flow
    cfg = {"web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }}
    return Flow.from_client_config(cfg, scopes=SCOPES, state=state,
                                   redirect_uri=os.getenv("GOOGLE_REDIRECT_URI"))


def auth_url(s: Session) -> str:
    if not configured():
        raise ValueError("Faltan GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET en la configuración del servidor.")
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    tok = s.get(GoogleToken, 1) or GoogleToken(id=1)
    tok.pending_state, tok.pending_verifier = state, flow.code_verifier or ""
    s.add(tok)
    s.commit()
    return url


def finish_auth(s: Session, code: str, state: str) -> None:
    tok = s.get(GoogleToken, 1)
    if not tok or not tok.pending_state or tok.pending_state != state:
        raise ValueError("Estado OAuth inválido. Volvé a intentar la conexión.")
    flow = _flow(state)
    flow.code_verifier = tok.pending_verifier or None
    flow.fetch_token(code=code)
    tok.credentials_json = flow.credentials.to_json()
    tok.pending_state = tok.pending_verifier = ""
    s.add(tok)
    s.commit()


def connected(s: Session) -> bool:
    tok = s.get(GoogleToken, 1)
    return bool(tok and tok.credentials_json)


def disconnect(s: Session) -> None:
    tok = s.get(GoogleToken, 1)
    if tok:
        tok.credentials_json = ""
        s.add(tok)
        s.commit()


def _creds(s: Session):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    tok = s.get(GoogleToken, 1)
    if not tok or not tok.credentials_json:
        raise ValueError("Google no está conectado. Conectalo desde Ajustes.")
    creds = Credentials.from_authorized_user_info(json.loads(tok.credentials_json), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        tok.credentials_json = creds.to_json()
        s.add(tok)
        s.commit()
    return creds


def _service(s: Session, name: str, version: str):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_creds(s), cache_discovery=False)


def _local_iso(value: str, s: Session) -> str:
    st = get_settings(s)
    return calc.to_local(calc.parse_dt(value, st), st).isoformat()


def create_event(s: Session, titulo: str, inicio: str, fin: Optional[str] = None, descripcion: str = "",
                 recordatorio_minutos: Optional[int] = 10, todo_el_dia: bool = False) -> dict:
    st = get_settings(s)
    if todo_el_dia:
        d = inicio[:10]
        end_d = (fin or "")[:10] or (datetime.fromisoformat(d) + timedelta(days=1)).date().isoformat()
        body = {"start": {"date": d}, "end": {"date": end_d}}
    else:
        start_iso = _local_iso(inicio, s)
        end_iso = _local_iso(fin, s) if fin else (datetime.fromisoformat(start_iso) + timedelta(minutes=30)).isoformat()
        body = {"start": {"dateTime": start_iso, "timeZone": st.timezone},
                "end": {"dateTime": end_iso, "timeZone": st.timezone}}
    body.update({"summary": titulo, "description": descripcion})
    if recordatorio_minutos is not None:
        body["reminders"] = {"useDefault": False,
                             "overrides": [{"method": "popup", "minutes": int(recordatorio_minutos)}]}
    ev = _service(s, "calendar", "v3").events().insert(calendarId="primary", body=body).execute()
    return {"id": ev.get("id"), "enlace": ev.get("htmlLink"), "titulo": titulo, "inicio": body["start"]}


def list_events(s: Session, desde: Optional[str] = None, hasta: Optional[str] = None, max_results: int = 15) -> list:
    st = get_settings(s)
    t_min = _local_iso(desde + "T00:00" if desde and len(desde) == 10 else (desde or datetime.now(calc.tz(st)).isoformat()), s)
    params = {"calendarId": "primary", "timeMin": t_min, "singleEvents": True, "orderBy": "startTime",
              "maxResults": max_results}
    if hasta:
        params["timeMax"] = _local_iso(hasta + "T23:59:59" if len(hasta) == 10 else hasta, s)
    items = _service(s, "calendar", "v3").events().list(**params).execute().get("items", [])
    return [{"id": e.get("id"), "titulo": e.get("summary", "(sin título)"),
             "inicio": e["start"].get("dateTime", e["start"].get("date")),
             "fin": e["end"].get("dateTime", e["end"].get("date"))} for e in items]


def create_task(s: Session, titulo: str, fecha: Optional[str] = None, notas: str = "") -> dict:
    body = {"title": titulo, "notes": notas}
    if fecha:
        # La API de Google Tasks solo guarda la fecha (la hora se ignora).
        body["due"] = fecha[:10] + "T00:00:00.000Z"
    t = _service(s, "tasks", "v1").tasks().insert(tasklist="@default", body=body).execute()
    return {"id": t.get("id"), "titulo": titulo, "fecha": fecha}
