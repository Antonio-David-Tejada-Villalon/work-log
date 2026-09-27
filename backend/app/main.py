"""API FastAPI de Control Horario + Banco de Horas. También sirve la PWA compilada (frontend/dist)."""
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlmodel import Session

from . import assistant, calc
from . import google_integration as gi
from .db import get_session, get_settings, init_db
from .excel import build_xlsx

APP_PIN = os.getenv("APP_PIN", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Control Horario", version="1.0.0", lifespan=lifespan)


def auth(x_app_pin: Optional[str] = Header(default=None), pin: Optional[str] = Query(default=None)) -> None:
    if APP_PIN and (x_app_pin or pin) != APP_PIN:
        raise HTTPException(401, "PIN incorrecto")


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


R = Depends(auth)


# ---------------------------------------------------------------- estado general
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status", dependencies=[R])
def status(s: Session = Depends(get_session)):
    st = get_settings(s)
    t = calc.today(st).isoformat()
    op = calc.open_shift(s)
    hoy = calc.daily_summary(s, t, t)
    return {
        "hoy": t,
        "en_curso": calc.shift_out(op, st) if op else None,
        "resumen_hoy": hoy[0] if hoy else None,
        "banco": {k: v for k, v in calc.bank_status(s).items() if k != "movimientos"},
        "ajustes": st.model_dump(),
        "google": {"configurado": gi.configured(), "conectado": gi.connected(s)},
        "ia": bool(os.getenv("GEMINI_API_KEY")),
    }


# ---------------------------------------------------------------- jornadas
@app.post("/api/clock-in", dependencies=[R])
def clock_in(body: ClockIn, s: Session = Depends(get_session)):
    return guard(lambda: calc.shift_out(calc.clock_in(s, body.hora, body.nota), get_settings(s)))


@app.post("/api/clock-out", dependencies=[R])
def clock_out(body: ClockIn, s: Session = Depends(get_session)):
    return guard(lambda: calc.shift_out(calc.clock_out(s, body.hora, body.nota), get_settings(s)))


@app.get("/api/shifts", dependencies=[R])
def shifts(desde: Optional[str] = None, hasta: Optional[str] = None, s: Session = Depends(get_session)):
    st = get_settings(s)
    return [calc.shift_out(x, st) for x in guard(lambda: calc.list_shifts(s, desde, hasta))]


@app.post("/api/shifts", dependencies=[R])
def create_shift(body: ShiftIn, s: Session = Depends(get_session)):
    if not body.inicio:
        raise HTTPException(400, "Falta la hora de inicio")
    return guard(lambda: calc.shift_out(calc.create_shift(s, body.fecha, body.inicio, body.fin, body.nota or ""),
                                        get_settings(s)))


@app.put("/api/shifts/{shift_id}", dependencies=[R])
def update_shift(shift_id: int, body: ShiftIn, s: Session = Depends(get_session)):
    return guard(lambda: calc.shift_out(
        calc.update_shift(s, shift_id, body.fecha, body.inicio, body.fin, body.nota), get_settings(s)))


@app.delete("/api/shifts/{shift_id}", dependencies=[R])
def delete_shift(shift_id: int, s: Session = Depends(get_session)):
    guard(lambda: calc.delete_shift(s, shift_id))
    return {"ok": True}


# ---------------------------------------------------------------- resumen / extras
@app.get("/api/summary", dependencies=[R])
def summary(desde: Optional[str] = None, hasta: Optional[str] = None, s: Session = Depends(get_session)):
    return {"totales": calc.totals(s, desde, hasta), "dias": calc.daily_summary(s, desde, hasta)}


@app.put("/api/days/{day}/extra", dependencies=[R])
def set_extra(day: str, body: DayExtraIn, s: Session = Depends(get_session)):
    secs = None if body.horas is None else int(round(body.horas * 3600 + body.minutos * 60))
    guard(lambda: calc.set_day_extra(s, day, secs, body.nota))
    return {"ok": True}


# ---------------------------------------------------------------- banco de horas
@app.get("/api/bank", dependencies=[R])
def bank(s: Session = Depends(get_session)):
    return calc.bank_status(s)


@app.post("/api/bank", dependencies=[R])
def bank_add(body: BankIn, s: Session = Depends(get_session)):
    if body.tipo not in ("uso", "ajuste"):
        raise HTTPException(400, "tipo debe ser 'uso' o 'ajuste'")
    return guard(lambda: calc.mov_out(calc.add_bank_movement(s, body.fecha, body.horas, body.dias, body.minutos,
                                                             body.tipo, body.nota)))


@app.put("/api/bank/{mov_id}", dependencies=[R])
def bank_edit(mov_id: int, body: BankEdit, s: Session = Depends(get_session)):
    secs = None if body.horas is None else int(round(body.horas * 3600 + body.minutos * 60))
    return guard(lambda: calc.mov_out(calc.update_bank_movement(s, mov_id, body.fecha, secs, body.nota)))


@app.delete("/api/bank/{mov_id}", dependencies=[R])
def bank_delete(mov_id: int, s: Session = Depends(get_session)):
    guard(lambda: calc.delete_bank_movement(s, mov_id))
    return {"ok": True}


# ---------------------------------------------------------------- ajustes
@app.get("/api/settings", dependencies=[R])
def get_cfg(s: Session = Depends(get_session)):
    return get_settings(s).model_dump()


@app.put("/api/settings", dependencies=[R])
def put_cfg(body: SettingsIn, s: Session = Depends(get_session)):
    st = get_settings(s)
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
@app.get("/api/export.xlsx", dependencies=[R])
def export(desde: Optional[str] = None, hasta: Optional[str] = None, s: Session = Depends(get_session)):
    data = build_xlsx(s, desde, hasta)
    name = f"control_horario_{date.today().isoformat()}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- IA
@app.post("/api/assistant", dependencies=[R])
def ai(body: ChatIn, s: Session = Depends(get_session)):
    try:
        return assistant.chat(s, body.mensaje, body.historial)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Error del asistente: {e}") from e


# ---------------------------------------------------------------- Google
@app.get("/api/google/auth-url", dependencies=[R])
def google_url(s: Session = Depends(get_session)):
    return {"url": guard(lambda: gi.auth_url(s))}


@app.get("/api/google/callback")
def google_callback(code: str = "", state: str = "", error: str = "", s: Session = Depends(get_session)):
    base = FRONTEND_URL or "/"
    if error or not code:
        return RedirectResponse(f"{base}?google=error")
    try:
        gi.finish_auth(s, code, state)
    except Exception:  # noqa: BLE001
        return RedirectResponse(f"{base}?google=error")
    return RedirectResponse(f"{base}?google=ok")


@app.post("/api/google/disconnect", dependencies=[R])
def google_disconnect(s: Session = Depends(get_session)):
    gi.disconnect(s)
    return {"ok": True}


# ---------------------------------------------------------------- frontend compilado (frontend/dist)
# app.frontend sirve la PWA con menor prioridad que la API; en Vercel se publica en su CDN.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.frontend("/", directory=DIST, fallback="index.html")
