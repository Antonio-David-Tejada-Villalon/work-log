"""Alarmas que suenan dentro de la app (repeticiones, sonido y aviso por voz del motivo).

Cada alarma se refuerza con un evento en Google Calendar cuando el usuario tiene Google conectado, así llega una
notificación aunque la app esté cerrada. Ese refuerzo es "best-effort": si Calendar falla, la alarma en la app
sigue funcionando igual. La app nunca sabe si esa notificación despertó a nadie; eso solo lo sabe con certeza la
confirmación dentro de la propia app (dismiss_alarm).
"""
from datetime import timezone
from typing import Optional

from sqlmodel import Session, select

from . import calc
from . import google_integration as gi
from .db import Alarm, get_settings, utcnow

SOUNDS = ("clasica", "suave", "urgente")
MIN_REPEAT, MAX_REPEAT = 1, 30
MIN_INTERVAL, MAX_INTERVAL = 3, 3600


def _validate(name: str, repeat_count: int, interval_seconds: int, sound: str) -> None:
    if not (name or "").strip():
        raise ValueError("Ponele un nombre a la alarma.")
    if len(name) > 100:
        raise ValueError("El nombre es demasiado largo (máximo 100 caracteres).")
    if not MIN_REPEAT <= repeat_count <= MAX_REPEAT:
        raise ValueError(f"Las repeticiones deben estar entre {MIN_REPEAT} y {MAX_REPEAT}.")
    if not MIN_INTERVAL <= interval_seconds <= MAX_INTERVAL:
        raise ValueError(f"El intervalo debe estar entre {MIN_INTERVAL} y {MAX_INTERVAL} segundos.")
    if sound not in SOUNDS:
        raise ValueError(f"El sonido debe ser uno de: {', '.join(SOUNDS)}.")


def out(a: Alarm, st) -> dict:
    return {
        "id": a.id,
        "nombre": a.name,
        "motivo": a.motivo or a.name,
        "hora": calc.to_local(a.run_at, st).isoformat(timespec="seconds"),
        "sonido": a.sound,
        "veces": a.repeat_count,
        "intervalo_segundos": a.interval_seconds,
        "en_calendar": bool(a.calendar_event_id),
        "confirmada": a.dismissed_at is not None,
        "pasada": a.run_at <= utcnow(),
    }


def list_alarms(s: Session, uid: int) -> list[Alarm]:
    return list(s.exec(select(Alarm).where(Alarm.user_id == uid).order_by(Alarm.run_at)).all())


def _own_alarm(s: Session, uid: int, alarm_id: int) -> Alarm:
    a = s.get(Alarm, alarm_id)
    if not a or a.user_id != uid:  # una alarma ajena se trata como inexistente
        raise ValueError(f"No existe la alarma {alarm_id}.")
    return a


def _sync_calendar(s: Session, uid: int, a: Alarm, creating: bool = False) -> None:
    """Refuerzo best-effort: si Calendar no está conectado o la llamada falla, la alarma sigue funcionando igual."""
    if not gi.connected(s, uid):
        return
    try:
        inicio = a.run_at.replace(tzinfo=timezone.utc).isoformat()
        titulo, descripcion = f"⏰ {a.name}", (a.motivo or a.name)
        if creating or not a.calendar_event_id:
            ev = gi.create_event(s, uid, titulo, inicio, descripcion=descripcion, recordatorio_minutos=0)
            a.calendar_event_id = ev["id"]
        else:
            gi.update_event(s, uid, a.calendar_event_id, titulo=titulo, inicio=inicio, descripcion=descripcion,
                            recordatorio_minutos=0)
        s.add(a)
        s.commit()
    except Exception:  # noqa: BLE001
        pass


def create_alarm(s: Session, uid: int, name: str, cuando: str, motivo: str = "", sound: str = "clasica",
                 repeat_count: int = 5, interval_seconds: int = 15) -> Alarm:
    st = get_settings(s, uid)
    _validate(name, repeat_count, interval_seconds, sound)
    a = Alarm(user_id=uid, name=name.strip(), motivo=motivo.strip(), run_at=calc.parse_dt(cuando, st), sound=sound,
             repeat_count=repeat_count, interval_seconds=interval_seconds)
    s.add(a)
    s.commit()
    s.refresh(a)
    _sync_calendar(s, uid, a, creating=True)
    return a


def update_alarm(s: Session, uid: int, alarm_id: int, name: Optional[str] = None, cuando: Optional[str] = None,
                 motivo: Optional[str] = None, sound: Optional[str] = None, repeat_count: Optional[int] = None,
                 interval_seconds: Optional[int] = None) -> Alarm:
    st = get_settings(s, uid)
    a = _own_alarm(s, uid, alarm_id)
    _validate(name if name is not None else a.name, repeat_count if repeat_count is not None else a.repeat_count,
             interval_seconds if interval_seconds is not None else a.interval_seconds,
             sound if sound is not None else a.sound)
    if name is not None:
        a.name = name.strip()
    if motivo is not None:
        a.motivo = motivo.strip()
    if cuando is not None:
        a.run_at = calc.parse_dt(cuando, st)
        a.dismissed_at = None  # se reprograma: vuelve a quedar pendiente
    if sound is not None:
        a.sound = sound
    if repeat_count is not None:
        a.repeat_count = repeat_count
    if interval_seconds is not None:
        a.interval_seconds = interval_seconds
    s.add(a)
    s.commit()
    s.refresh(a)
    _sync_calendar(s, uid, a)
    return a


def delete_alarm(s: Session, uid: int, alarm_id: int) -> None:
    a = _own_alarm(s, uid, alarm_id)
    if a.calendar_event_id:
        try:
            gi.delete_event(s, uid, a.calendar_event_id)
        except Exception:  # noqa: BLE001
            pass
    s.delete(a)
    s.commit()


def dismiss_alarm(s: Session, uid: int, alarm_id: int) -> Alarm:
    """Confirma que la persona la vio/se despertó. Es la única fuente confiable de esa confirmación."""
    a = _own_alarm(s, uid, alarm_id)
    a.dismissed_at = utcnow()
    s.add(a)
    s.commit()
    s.refresh(a)
    return a
