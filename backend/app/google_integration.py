"""Inicio de sesión con Google + integración con Google Calendar (eventos y recordatorios) y Google Tasks (tareas).

Un solo permiso de Google cubre la identidad (correo) y el acceso a Calendar y Tasks de cada usuario.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from . import auth, calc
from .db import GoogleToken, OAuthState, User, get_settings, utcnow

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]
STATE_TTL = timedelta(minutes=30)


class AccessDenied(Exception):
    """La cuenta de Google es válida pero el dueño la bloqueó."""


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


def _verify_id_token(token: str) -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(token, Request(), os.getenv("GOOGLE_CLIENT_ID"))


# ---------------------------------------------------------------- inicio de sesión
def start_login(s: Session) -> str:
    """Devuelve la URL de Google a la que hay que enviar al usuario."""
    if not configured():
        raise ValueError("Faltan GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET en la configuración del servidor.")
    if not auth.owner_email():
        raise ValueError("Falta OWNER_EMAIL en la configuración del servidor.")
    for old in s.exec(select(OAuthState).where(OAuthState.created_at <= utcnow() - STATE_TTL)).all():
        s.delete(old)
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    s.add(OAuthState(state=state, verifier=flow.code_verifier or ""))
    s.commit()
    return url


def finish_login(s: Session, code: str, state: str) -> User:
    """Completa el ingreso: valida el estado, verifica el correo con Google y guarda los permisos."""
    st = s.get(OAuthState, state)
    if not st or st.created_at <= utcnow() - STATE_TTL:
        raise ValueError("Estado OAuth inválido. Volvé a intentar el ingreso.")
    verifier = st.verifier
    s.delete(st)  # se usa una sola vez
    s.commit()
    flow = _flow(state)
    flow.code_verifier = verifier or None
    flow.fetch_token(code=code)
    creds = flow.credentials
    info = _verify_id_token(creds.id_token)
    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified"):
        raise ValueError("Google no confirmó tu correo.")
    if not auth.is_allowed(s, email):
        raise AccessDenied(email)  # cuenta bloqueada: no se crea nada ni se guardan sus permisos
    user = s.exec(select(User).where(User.email == email)).first() or User(email=email)
    user.name = info.get("name") or user.name or email.split("@")[0]
    user.picture = info.get("picture") or user.picture
    user.last_login = utcnow()
    s.add(user)
    s.commit()
    s.refresh(user)
    get_settings(s, user.id)  # crea los ajustes por defecto la primera vez
    _save_credentials(s, user.id, creds)
    return user


# ---------------------------------------------------------------- credenciales de cada usuario
def _save_credentials(s: Session, uid: int, creds) -> None:
    data = json.loads(creds.to_json())
    tok = s.get(GoogleToken, uid) or GoogleToken(user_id=uid)
    if not data.get("refresh_token") and tok.credentials_json:  # Google solo lo envía en el primer consentimiento
        data["refresh_token"] = json.loads(tok.credentials_json).get("refresh_token")
    tok.credentials_json = json.dumps(data)
    s.add(tok)
    s.commit()


def connected(s: Session, uid: int) -> bool:
    tok = s.get(GoogleToken, uid)
    return bool(tok and tok.credentials_json)


def disconnect(s: Session, uid: int) -> None:
    tok = s.get(GoogleToken, uid)
    if not tok or not tok.credentials_json:
        return
    try:  # avisa a Google para que deje de valer el permiso; si falla igual se olvida acá
        import requests
        info = json.loads(tok.credentials_json)
        requests.post("https://oauth2.googleapis.com/revoke", params={"token": info.get("refresh_token") or info.get("token")},
                      timeout=5)
    except Exception:  # noqa: BLE001
        pass
    tok.credentials_json = ""
    s.add(tok)
    s.commit()


def _creds(s: Session, uid: int):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    tok = s.get(GoogleToken, uid)
    if not tok or not tok.credentials_json:
        raise ValueError("Google no está conectado. Cerrá sesión y volvé a entrar con Google.")
    info = json.loads(tok.credentials_json)
    info.pop("scopes", None)  # se usan los permisos que el usuario realmente otorgó
    creds = Credentials.from_authorized_user_info(info)
    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            tok.credentials_json = ""
            s.add(tok)
            s.commit()
            raise ValueError("Tu conexión con Google venció. Cerrá sesión y volvé a entrar con Google.") from e
        tok.credentials_json = creds.to_json()
        s.add(tok)
        s.commit()
    return creds


def _service(s: Session, uid: int, name: str, version: str):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_creds(s, uid), cache_discovery=False)


# ---------------------------------------------------------------- Calendar y Tasks
def _local_iso(value: str, s: Session, uid: int) -> str:
    st = get_settings(s, uid)
    return calc.to_local(calc.parse_dt(value, st), st).isoformat()


def create_event(s: Session, uid: int, titulo: str, inicio: str, fin: Optional[str] = None, descripcion: str = "",
                 recordatorio_minutos: Optional[int] = 10, todo_el_dia: bool = False) -> dict:
    st = get_settings(s, uid)
    if todo_el_dia:
        d = inicio[:10]
        end_d = (fin or "")[:10] or (datetime.fromisoformat(d) + timedelta(days=1)).date().isoformat()
        body = {"start": {"date": d}, "end": {"date": end_d}}
    else:
        start_iso = _local_iso(inicio, s, uid)
        end_iso = _local_iso(fin, s, uid) if fin else (datetime.fromisoformat(start_iso) + timedelta(minutes=30)).isoformat()
        body = {"start": {"dateTime": start_iso, "timeZone": st.timezone},
                "end": {"dateTime": end_iso, "timeZone": st.timezone}}
    body.update({"summary": titulo, "description": descripcion})
    if recordatorio_minutos is not None:
        body["reminders"] = {"useDefault": False,
                             "overrides": [{"method": "popup", "minutes": int(recordatorio_minutos)}]}
    ev = _service(s, uid, "calendar", "v3").events().insert(calendarId="primary", body=body).execute()
    return {"id": ev.get("id"), "enlace": ev.get("htmlLink"), "titulo": titulo, "inicio": body["start"]}


def update_event(s: Session, uid: int, event_id: str, titulo: Optional[str] = None, inicio: Optional[str] = None,
                 fin: Optional[str] = None, descripcion: Optional[str] = None,
                 recordatorio_minutos: Optional[int] = None) -> dict:
    body: dict = {}
    if titulo is not None:
        body["summary"] = titulo
    if descripcion is not None:
        body["description"] = descripcion
    if inicio is not None:
        st = get_settings(s, uid)
        start_iso = _local_iso(inicio, s, uid)
        end_iso = _local_iso(fin, s, uid) if fin else (datetime.fromisoformat(start_iso) + timedelta(minutes=30)).isoformat()
        body["start"] = {"dateTime": start_iso, "timeZone": st.timezone}
        body["end"] = {"dateTime": end_iso, "timeZone": st.timezone}
    if recordatorio_minutos is not None:
        body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(recordatorio_minutos)}]}
    ev = _service(s, uid, "calendar", "v3").events().patch(calendarId="primary", eventId=event_id, body=body).execute()
    return {"id": ev.get("id"), "enlace": ev.get("htmlLink"), "titulo": ev.get("summary"), "inicio": ev.get("start")}


def delete_event(s: Session, uid: int, event_id: str) -> None:
    from googleapiclient.errors import HttpError
    try:
        _service(s, uid, "calendar", "v3").events().delete(calendarId="primary", eventId=event_id).execute()
    except HttpError as e:
        if e.resp.status not in (404, 410):  # ya no existe: no es un error para quien nos pidió borrarlo
            raise


def list_events(s: Session, uid: int, desde: Optional[str] = None, hasta: Optional[str] = None,
                max_results: int = 15) -> list:
    st = get_settings(s, uid)
    t_min = _local_iso(desde + "T00:00" if desde and len(desde) == 10 else (desde or datetime.now(calc.tz(st)).isoformat()), s, uid)
    params = {"calendarId": "primary", "timeMin": t_min, "singleEvents": True, "orderBy": "startTime",
              "maxResults": max_results}
    if hasta:
        params["timeMax"] = _local_iso(hasta + "T23:59:59" if len(hasta) == 10 else hasta, s, uid)
    items = _service(s, uid, "calendar", "v3").events().list(**params).execute().get("items", [])
    return [{"id": e.get("id"), "titulo": e.get("summary", "(sin título)"),
             "inicio": e["start"].get("dateTime", e["start"].get("date")),
             "fin": e["end"].get("dateTime", e["end"].get("date"))} for e in items]


def create_task(s: Session, uid: int, titulo: str, fecha: Optional[str] = None, notas: str = "") -> dict:
    body = {"title": titulo, "notes": notas}
    if fecha:
        # La API de Google Tasks solo guarda la fecha (la hora se ignora).
        body["due"] = fecha[:10] + "T00:00:00.000Z"
    t = _service(s, uid, "tasks", "v1").tasks().insert(tasklist="@default", body=body).execute()
    return {"id": t.get("id"), "titulo": titulo, "fecha": fecha}
