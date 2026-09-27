"""API FastAPI de Control Horario + Banco de Horas (multiusuario). También sirve la PWA compilada (frontend/dist)."""
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlmodel import Session

from . import assistant, auth, calc
from . import google_integration as gi
from .db import User, get_session, get_settings, init_db
from .excel import build_xlsx

FRONTEND_URL = os.getenv("FRONTEND_URL", "")

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Control Horario", version="2.0.0", lifespan=lifespan)


def current_user(request: Request, s: Session = Depends(get_session)) -> User:
    """Usuario de la sesión (cookie). Si ya no está invitado, la sesión deja de servir."""
    u = auth.user_for_token(s, request.cookies.get(auth.COOKIE))
    if not u or not auth.is_allowed(s, u.email):
        raise HTTPException(401, "Iniciá sesión con Google para continuar.")
    return u


def owner_only(u: User = Depends(current_user)) -> User:
    if not auth.is_owner(u.email):
        raise HTTPException(403, "Solo el dueño de la app puede hacer esto.")
    return u


def guard(fn):
    """Convierte ValueError de la lógica de negocio en HTTP 400 con el mensaje."""
    try:
        return fn()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------- esquemas
class ClockIn(BaseModel):
    hora: Optional[str] = None
    nota: str = ""


class ShiftIn(BaseModel):
    fecha: Optional[str] = None
    inicio: Optional[str] = None
    fin: Optional[str] = None
    nota: Optional[str] = None


class SettingsIn(BaseModel):
    daily_hours: Optional[float] = None
    workdays_per_month: Optional[int] = None
    count_deficit: Optional[bool] = None
    timezone: Optional[str] = None


class DayExtraIn(BaseModel):
    horas: Optional[float] = None   # None = quitar corrección
    minutos: float = 0
    nota: str = ""


class BankIn(BaseModel):
    fecha: str
    dias: float = 0
    horas: float = 0
    minutos: float = 0
    tipo: str = "uso"               # uso | ajuste
    nota: str = ""


class BankEdit(BaseModel):
    fecha: Optional[str] = None
    horas: Optional[float] = None
    minutos: float = 0
    nota: Optional[str] = None


class ChatIn(BaseModel):
    mensaje: str
    historial: list[dict] = []


class InviteIn(BaseModel):
    email: str


# ---------------------------------------------------------------- estado general
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status(u: User = Depends(current_user), s: Session = Depends(get_session)):
    st = get_settings(s, u.id)
    t = calc.today(st).isoformat()
    op = calc.open_shift(s, u.id)
    hoy = calc.daily_summary(s, u.id, t, t)
    return {
        "hoy": t,
        "usuario": {"email": u.email, "nombre": u.name, "foto": u.picture, "es_dueno": auth.is_owner(u.email)},
        "en_curso": calc.shift_out(op, st) if op else None,
        "resumen_hoy": hoy[0] if hoy else None,
        "banco": {k: v for k, v in calc.bank_status(s, u.id).items() if k != "movimientos"},
        "ajustes": st.model_dump(),
        "google": {"configurado": gi.configured(), "conectado": gi.connected(s, u.id)},
        "ia": bool(os.getenv("GEMINI_API_KEY")),
    }


# ---------------------------------------------------------------- jornadas
@app.post("/api/clock-in")
def clock_in(body: ClockIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    return guard(lambda: calc.shift_out(calc.clock_in(s, u.id, body.hora, body.nota), get_settings(s, u.id)))


@app.post("/api/clock-out")
def clock_out(body: ClockIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    return guard(lambda: calc.shift_out(calc.clock_out(s, u.id, body.hora, body.nota), get_settings(s, u.id)))


@app.get("/api/shifts")
def shifts(desde: Optional[str] = None, hasta: Optional[str] = None, u: User = Depends(current_user),
           s: Session = Depends(get_session)):
    st = get_settings(s, u.id)
    return [calc.shift_out(x, st) for x in guard(lambda: calc.list_shifts(s, u.id, desde, hasta))]


@app.post("/api/shifts")
def create_shift(body: ShiftIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    if not body.inicio:
        raise HTTPException(400, "Falta la hora de inicio")
    return guard(lambda: calc.shift_out(calc.create_shift(s, u.id, body.fecha, body.inicio, body.fin, body.nota or ""),
                                        get_settings(s, u.id)))


@app.put("/api/shifts/{shift_id}")
def update_shift(shift_id: int, body: ShiftIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    return guard(lambda: calc.shift_out(
        calc.update_shift(s, u.id, shift_id, body.fecha, body.inicio, body.fin, body.nota), get_settings(s, u.id)))


@app.delete("/api/shifts/{shift_id}")
def delete_shift(shift_id: int, u: User = Depends(current_user), s: Session = Depends(get_session)):
    guard(lambda: calc.delete_shift(s, u.id, shift_id))
    return {"ok": True}


# ---------------------------------------------------------------- resumen / extras
@app.get("/api/summary")
def summary(desde: Optional[str] = None, hasta: Optional[str] = None, u: User = Depends(current_user),
            s: Session = Depends(get_session)):
    return {"totales": calc.totals(s, u.id, desde, hasta), "dias": calc.daily_summary(s, u.id, desde, hasta)}


@app.put("/api/days/{day}/extra")
def set_extra(day: str, body: DayExtraIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    secs = None if body.horas is None else int(round(body.horas * 3600 + body.minutos * 60))
    guard(lambda: calc.set_day_extra(s, u.id, day, secs, body.nota))
    return {"ok": True}


# ---------------------------------------------------------------- banco de horas
@app.get("/api/bank")
def bank(u: User = Depends(current_user), s: Session = Depends(get_session)):
    return calc.bank_status(s, u.id)


@app.post("/api/bank")
def bank_add(body: BankIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    if body.tipo not in ("uso", "ajuste"):
        raise HTTPException(400, "tipo debe ser 'uso' o 'ajuste'")
    return guard(lambda: calc.mov_out(calc.add_bank_movement(s, u.id, body.fecha, body.horas, body.dias, body.minutos,
                                                             body.tipo, body.nota)))


@app.put("/api/bank/{mov_id}")
def bank_edit(mov_id: int, body: BankEdit, u: User = Depends(current_user), s: Session = Depends(get_session)):
    secs = None if body.horas is None else int(round(body.horas * 3600 + body.minutos * 60))
    return guard(lambda: calc.mov_out(calc.update_bank_movement(s, u.id, mov_id, body.fecha, secs, body.nota)))


@app.delete("/api/bank/{mov_id}")
def bank_delete(mov_id: int, u: User = Depends(current_user), s: Session = Depends(get_session)):
    guard(lambda: calc.delete_bank_movement(s, u.id, mov_id))
    return {"ok": True}


# ---------------------------------------------------------------- ajustes
@app.get("/api/settings")
def get_cfg(u: User = Depends(current_user), s: Session = Depends(get_session)):
    return get_settings(s, u.id).model_dump()


@app.put("/api/settings")
def put_cfg(body: SettingsIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    st = get_settings(s, u.id)
    data = body.model_dump(exclude_none=True)
    if "timezone" in data:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(data["timezone"])
        except Exception as e:
            raise HTTPException(400, "Zona horaria inválida") from e
    if data.get("daily_hours", 1) <= 0 or data.get("workdays_per_month", 1) <= 0:
        raise HTTPException(400, "Los valores deben ser mayores que cero")
    for k, v in data.items():
        setattr(st, k, v)
    s.add(st)
    s.commit()
    s.refresh(st)
    return st.model_dump()


# ---------------------------------------------------------------- Excel
@app.get("/api/export.xlsx")
def export(desde: Optional[str] = None, hasta: Optional[str] = None, u: User = Depends(current_user),
           s: Session = Depends(get_session)):
    data = build_xlsx(s, u.id, desde, hasta)
    name = f"control_horario_{date.today().isoformat()}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- IA
@app.post("/api/assistant")
def ai(body: ChatIn, u: User = Depends(current_user), s: Session = Depends(get_session)):
    try:
        return assistant.chat(s, u, body.mensaje, body.historial)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Error del asistente: {e}") from e


# ---------------------------------------------------------------- ingreso con Google y sesión
def _redirect(param: str) -> RedirectResponse:
    return RedirectResponse(f"{FRONTEND_URL or '/'}?login={param}")


@app.get("/api/auth/google/start")
def google_start(s: Session = Depends(get_session)):
    try:
        return RedirectResponse(gi.start_login(s))
    except ValueError:
        return _redirect("config")


@app.get("/api/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = "",
                    s: Session = Depends(get_session)):
    if error or not code:
        return _redirect("error")
    try:
        user = gi.finish_login(s, code, state)
    except gi.AccessDenied:
        return _redirect("denied")
    except Exception:  # noqa: BLE001
        return _redirect("error")
    resp = _redirect("ok")
    secure = FRONTEND_URL.startswith("https") or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(auth.COOKIE, auth.create_session(s, user.id), max_age=auth.SESSION_DAYS * 86400,
                    httponly=True, secure=secure, samesite="lax", path="/")
    return resp


@app.post("/api/auth/logout")
def logout(request: Request, s: Session = Depends(get_session)):
    auth.end_session(s, request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.post("/api/google/disconnect")
def google_disconnect(u: User = Depends(current_user), s: Session = Depends(get_session)):
    gi.disconnect(s, u.id)
    return {"ok": True}


# ---------------------------------------------------------------- invitados (solo el dueño)
@app.get("/api/admin/invitados")
def invited(_: User = Depends(owner_only), s: Session = Depends(get_session)):
    return auth.list_invited(s)


@app.post("/api/admin/invitados")
def invite(body: InviteIn, _: User = Depends(owner_only), s: Session = Depends(get_session)):
    guard(lambda: auth.invite(s, body.email))
    return auth.list_invited(s)


@app.delete("/api/admin/invitados/{email}")
def uninvite(email: str, _: User = Depends(owner_only), s: Session = Depends(get_session)):
    guard(lambda: auth.revoke(s, email))
    return auth.list_invited(s)


# ---------------------------------------------------------------- frontend compilado (frontend/dist)
# app.frontend sirve la PWA con menor prioridad que la API; en Vercel se publica en su CDN.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.frontend("/", directory=DIST, fallback="index.html")
