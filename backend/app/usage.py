"""Uso de la IA (Gemini) por usuario y por día.

Google fija los topes por proyecto (todos los usuarios de la app comparten los mismos) y reinicia los diarios a la
medianoche del Pacífico de EE. UU.; por eso los días se cuentan en esa zona. Google no permite consultar por API cuánto
queda: acá se lleva la cuenta de lo consumido, y el tope real se ve en https://aistudio.google.com/rate-limit
"""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from .db import AiUsage, User

QUOTA_TZ = ZoneInfo("America/Los_Angeles")


def quota_day(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(QUOTA_TZ)).astimezone(QUOTA_TZ).date().isoformat()


def next_reset(tz: ZoneInfo, now: Optional[datetime] = None) -> datetime:
    """Próxima medianoche del Pacífico, expresada en la zona horaria dada."""
    now = (now or datetime.now(QUOTA_TZ)).astimezone(QUOTA_TZ)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(tz)


def record(s: Session, uid: int, prompt_tokens: Optional[int], total_tokens: Optional[int]) -> None:
    """Suma una solicitud exitosa a Gemini. Es solo informativo: nunca debe romper al asistente."""
    try:
        day = quota_day()
        row = s.get(AiUsage, (uid, day)) or AiUsage(user_id=uid, day=day)
        row.requests += 1
        row.prompt_tokens += prompt_tokens or 0
        row.output_tokens += max(0, (total_tokens or 0) - (prompt_tokens or 0))
        s.add(row)
        s.commit()
    except Exception:  # noqa: BLE001
        s.rollback()


def _out(r: Optional[AiUsage]) -> dict:
    return {"solicitudes": r.requests if r else 0, "tokens_entrada": r.prompt_tokens if r else 0,
            "tokens_salida": r.output_tokens if r else 0}


def report(s: Session, uid: int, owner: bool, tz: ZoneInfo) -> dict:
    """Uso de hoy del usuario; el dueño ve además el de cada persona y el total."""
    day = quota_day()
    out = {"dia": day, "reinicia": next_reset(tz).isoformat(timespec="minutes"), "yo": _out(s.get(AiUsage, (uid, day)))}
    if owner:
        rows = s.exec(select(AiUsage, User).join(User, User.id == AiUsage.user_id).where(AiUsage.day == day)).all()
        todos = sorted(({"email": u.email, "nombre": u.name, **_out(r)} for r, u in rows), key=lambda x: -x["solicitudes"])
        out["todos"] = todos
        out["total"] = {k: sum(x[k] for x in todos) for k in ("solicitudes", "tokens_entrada", "tokens_salida")}
    return out
