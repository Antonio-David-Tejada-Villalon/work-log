"""Lógica de negocio: fechas/horas locales, jornadas, horas extra y banco de horas."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from .db import BankMovement, DayOverride, Settings, Shift, get_settings, utcnow


# ---------------------------------------------------------------- zona horaria
def tz(st: Settings) -> ZoneInfo:
    return ZoneInfo(st.timezone)


def to_local(dt_utc: datetime, st: Settings) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(tz(st))


def parse_dt(value: str, st: Settings, base_day: Optional[date] = None) -> datetime:
    """Convierte un texto a datetime UTC naive.

    Acepta ISO con o sin zona ('2026-09-26T08:00', '2026-09-26T08:00-03:00')
    o solo hora 'HH:MM[:SS]' (usa base_day o la fecha local de hoy).
    Sin zona se interpreta en la zona horaria configurada.
    """
    value = value.strip().replace(" ", "T") if "-" in value else value.strip()
    if len(value) <= 8 and ":" in value:  # solo hora
        hh, _, rest = value.partition(":")
        value = f"{hh.zfill(2)}:{rest}"  # acepta '7:45' además de '07:45'
        t = time.fromisoformat(value if value.count(":") == 2 else value + ":00")
        d = base_day or datetime.now(tz(st)).date()
        local = datetime.combine(d, t, tzinfo=tz(st))
    else:
        local = datetime.fromisoformat(value)
        if local.tzinfo is None:
            local = local.replace(tzinfo=tz(st))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def local_day(dt_utc: datetime, st: Settings) -> date:
    return to_local(dt_utc, st).date()


def today(st: Settings) -> date:
    return datetime.now(tz(st)).date()


# ---------------------------------------------------------------- formatos
def hms(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    s = int(round(abs(seconds)))
    return f"{sign}{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def breakdown(seconds: float, unit_seconds: dict[str, int]) -> dict:
    """Descompone segundos en las unidades dadas (orden de mayor a menor)."""
    sign = -1 if seconds < 0 else 1
    rest = int(round(abs(seconds)))
    out = {}
    for name, size in unit_seconds.items():
        out[name], rest = divmod(rest, size) if size > 1 else (rest, 0)
    out["signo"] = sign
    return out


def bank_breakdowns(seconds: float, st: Settings) -> dict:
    day_s = int(round(st.daily_hours * 3600)) or 1
    return {
        # Días laborales = jornadas de st.daily_hours horas; mes = st.workdays_per_month jornadas
        "laboral": breakdown(seconds, {"meses": day_s * st.workdays_per_month, "dias": day_s,
                                       "horas": 3600, "minutos": 60, "segundos": 1}),
        # Tiempo reloj: día = 24 h; mes = 30 días
        "reloj": breakdown(seconds, {"meses": 30 * 86400, "dias": 86400, "horas": 3600,
                                     "minutos": 60, "segundos": 1}),
    }


# ---------------------------------------------------------------- jornadas
def shift_seconds(sh: Shift, now: Optional[datetime] = None) -> float:
    end = sh.end or (now or utcnow())
    return max(0.0, (end - sh.start).total_seconds())


def shift_out(sh: Shift, st: Settings) -> dict:
    return {
        "id": sh.id,
        "fecha": local_day(sh.start, st).isoformat(),
        "inicio": to_local(sh.start, st).isoformat(timespec="seconds"),
        "fin": to_local(sh.end, st).isoformat(timespec="seconds") if sh.end else None,
        "en_curso": sh.end is None,
        "segundos": int(shift_seconds(sh)),
        "duracion": hms(shift_seconds(sh)),
        "nota": sh.note,
    }


def open_shift(s: Session) -> Optional[Shift]:
    return s.exec(select(Shift).where(Shift.end == None).order_by(Shift.start.desc())).first()  # noqa: E711


def clock_in(s: Session, when: Optional[str] = None, note: str = "") -> Shift:
    st = get_settings(s)
    if open_shift(s):
        raise ValueError("Ya hay una jornada en curso. Registrá la salida primero.")
    sh = Shift(start=parse_dt(when, st) if when else utcnow().replace(microsecond=0), note=note)
    s.add(sh)
    s.commit()
    s.refresh(sh)
    return sh


def clock_out(s: Session, when: Optional[str] = None, note: str = "") -> Shift:
    st = get_settings(s)
    sh = open_shift(s)
    if not sh:
        raise ValueError("No hay una jornada en curso.")
    end = parse_dt(when, st, local_day(sh.start, st)) if when else utcnow().replace(microsecond=0)
    if end <= sh.start:
        raise ValueError("La hora de salida debe ser posterior a la de entrada.")
    sh.end = end
    if note:
        sh.note = (sh.note + " " + note).strip()
    s.add(sh)
    s.commit()
    s.refresh(sh)
    return sh


def create_shift(s: Session, day: Optional[str], start: str, end: Optional[str], note: str = "") -> Shift:
    st = get_settings(s)
    d = date.fromisoformat(day) if day else None
    sh = Shift(start=parse_dt(start, st, d), end=parse_dt(end, st, d) if end else None, note=note)
    if sh.end and sh.end <= sh.start:
        sh.end += timedelta(days=1)  # turno que cruza medianoche (p.ej. 22:00 → 06:00)
    s.add(sh)
    s.commit()
    s.refresh(sh)
    return sh


def update_shift(s: Session, shift_id: int, day: Optional[str] = None, start: Optional[str] = None,
                 end: Optional[str] = None, note: Optional[str] = None) -> Shift:
    st = get_settings(s)
    sh = s.get(Shift, shift_id)
    if not sh:
        raise ValueError(f"No existe la jornada {shift_id}.")
    base = date.fromisoformat(day) if day else local_day(sh.start, st)
    if start:
        sh.start = parse_dt(start, st, base)
    elif day:  # cambiar solo la fecha: conserva la hora local
        sh.start = parse_dt(to_local(sh.start, st).time().isoformat(), st, base)
    if end:
        sh.end = parse_dt(end, st, base)
    elif day and sh.end:
        sh.end = parse_dt(to_local(sh.end, st).time().isoformat(), st, base)
    if sh.end and sh.end <= sh.start:
        sh.end += timedelta(days=1)
    if note is not None:
        sh.note = note
    s.add(sh)
    s.commit()
    s.refresh(sh)
    return sh


def delete_shift(s: Session, shift_id: int) -> None:
    sh = s.get(Shift, shift_id)
    if not sh:
        raise ValueError(f"No existe la jornada {shift_id}.")
    s.delete(sh)
    s.commit()


def list_shifts(s: Session, desde: Optional[str] = None, hasta: Optional[str] = None) -> list[Shift]:
    st = get_settings(s)
    q = select(Shift).order_by(Shift.start)
    if desde:
        q = q.where(Shift.start >= parse_dt(desde + "T00:00", st))
    if hasta:
        q = q.where(Shift.start < parse_dt((date.fromisoformat(hasta) + timedelta(days=1)).isoformat() + "T00:00", st))
    return list(s.exec(q).all())


# ---------------------------------------------------------------- resumen diario y banco
def daily_summary(s: Session, desde: Optional[str] = None, hasta: Optional[str] = None) -> list[dict]:
    st = get_settings(s)
    target = st.daily_hours * 3600
    worked: dict[str, float] = defaultdict(float)
    for sh in list_shifts(s, desde, hasta):
        worked[local_day(sh.start, st).isoformat()] += shift_seconds(sh)
    overrides = {o.day: o for o in s.exec(select(DayOverride)).all()}
    days = sorted(set(worked) | {d for d in overrides if (not desde or d >= desde) and (not hasta or d <= hasta)})
    out = []
    for d in days:
        w = worked.get(d, 0.0)
        calc_extra = max(0.0, w - target)
        deficit = min(0.0, w - target) if (st.count_deficit and w > 0) else 0.0
        ov = overrides.get(d)
        extra = float(ov.extra_seconds) if ov else calc_extra
        out.append({
            "fecha": d,
            "trabajado_segundos": int(w), "trabajado": hms(w),
            "objetivo": hms(target),
            "extra_calculada": hms(calc_extra),
            "extra_segundos": int(extra), "extra": hms(extra),
            "faltante_segundos": int(deficit), "faltante": hms(deficit),
            "ajuste_manual": bool(ov), "nota_ajuste": ov.note if ov else "",
        })
    return out


def set_day_extra(s: Session, day: str, extra_seconds: Optional[int], note: str = "") -> None:
    """Fija manualmente las extras de un día. extra_seconds=None elimina la corrección."""
    date.fromisoformat(day)
    ov = s.get(DayOverride, day)
    if extra_seconds is None:
        if ov:
            s.delete(ov)
    else:
        ov = ov or DayOverride(day=day, extra_seconds=0)
        ov.extra_seconds, ov.note = int(extra_seconds), note
        s.add(ov)
    s.commit()


def bank_status(s: Session) -> dict:
    st = get_settings(s)
    days = daily_summary(s)
    extras = sum(d["extra_segundos"] for d in days)
    deficits = sum(d["faltante_segundos"] for d in days)
    movs = list(s.exec(select(BankMovement).order_by(BankMovement.day)).all())
    used = sum(m.seconds for m in movs if m.seconds < 0)
    adjust = sum(m.seconds for m in movs if m.seconds > 0)
    total = extras + deficits + used + adjust
    return {
        "saldo_segundos": int(total), "saldo": hms(total),
        "extras_acumuladas": hms(extras), "faltantes": hms(deficits),
        "usadas": hms(used), "ajustes_a_favor": hms(adjust),
        "desglose": bank_breakdowns(total, st),
        "jornada_horas": st.daily_hours, "dias_laborables_mes": st.workdays_per_month,
        "movimientos": [mov_out(m) for m in movs],
    }


def mov_out(m: BankMovement) -> dict:
    return {"id": m.id, "fecha": m.day, "segundos": m.seconds, "tiempo": hms(m.seconds),
            "tipo": m.kind, "nota": m.note}


def add_bank_movement(s: Session, day: str, hours: float = 0, days: float = 0, minutes: float = 0,
                      kind: str = "uso", note: str = "") -> BankMovement:
    """kind='uso' resta del banco; kind='ajuste' suma (o resta si el valor es negativo)."""
    st = get_settings(s)
    date.fromisoformat(day)
    secs = int(round(days * st.daily_hours * 3600 + hours * 3600 + minutes * 60))
    if secs == 0:
        raise ValueError("Indicá una cantidad de horas, minutos o días distinta de cero.")
    if kind == "uso":
        secs = -abs(secs)
    m = BankMovement(day=day, seconds=secs, kind=kind, note=note)
    s.add(m)
    s.commit()
    s.refresh(m)
    return m


def update_bank_movement(s: Session, mov_id: int, day: Optional[str] = None, seconds: Optional[int] = None,
                         note: Optional[str] = None) -> BankMovement:
    m = s.get(BankMovement, mov_id)
    if not m:
        raise ValueError(f"No existe el movimiento {mov_id}.")
    if day:
        date.fromisoformat(day)
        m.day = day
    if seconds is not None:
        m.seconds = -abs(seconds) if m.kind == "uso" else int(seconds)
    if note is not None:
        m.note = note
    s.add(m)
    s.commit()
    s.refresh(m)
    return m


def delete_bank_movement(s: Session, mov_id: int) -> None:
    m = s.get(BankMovement, mov_id)
    if not m:
        raise ValueError(f"No existe el movimiento {mov_id}.")
    s.delete(m)
    s.commit()


def totals(s: Session, desde: Optional[str], hasta: Optional[str]) -> dict:
    days = daily_summary(s, desde, hasta)
    w = sum(d["trabajado_segundos"] for d in days)
    e = sum(d["extra_segundos"] for d in days)
    return {"desde": desde, "hasta": hasta, "dias_trabajados": sum(1 for d in days if d["trabajado_segundos"] > 0),
            "trabajado": hms(w), "trabajado_segundos": w, "extras": hms(e), "extras_segundos": e}
