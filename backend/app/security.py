"""PIN de acceso. Se crea desde la app la primera vez (se guarda con hash y sal en la BD) y se puede cambiar.

APP_PIN es opcional: si se define, sirve además como PIN de respaldo (p. ej. para recuperar el acceso).
Tras MAX_FAILS intentos fallidos seguidos la app se bloquea LOCK para frenar la fuerza bruta.
"""
import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from functools import lru_cache
from typing import Optional

from sqlmodel import Session

from .db import AppPin, utcnow

MIN_LEN, MAX_LEN = 4, 64
MAX_FAILS = 5
LOCK = timedelta(seconds=60)


def env_pin() -> str:
    return os.getenv("APP_PIN", "").strip()


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 100_000).hex()


@lru_cache(maxsize=64)  # el hash es lento a propósito: se verifica una vez por PIN y por instancia
def _matches(pin: str, salt: str, digest: str) -> bool:
    return hmac.compare_digest(_hash(pin, salt), digest)


def _row(s: Session) -> AppPin:
    return s.get(AppPin, 1) or AppPin(id=1)


def is_configured(s: Session) -> bool:
    return bool(env_pin() or _row(s).digest)


def validate(pin: Optional[str]) -> str:
    pin = (pin or "").strip()
    if not MIN_LEN <= len(pin) <= MAX_LEN:
        raise ValueError(f"El PIN debe tener entre {MIN_LEN} y {MAX_LEN} caracteres.")
    if not pin.isascii() or not pin.isprintable():  # viaja en un encabezado HTTP
        raise ValueError("Usá solo letras, números y símbolos comunes (sin tildes ni emojis).")
    return pin


def set_pin(s: Session, pin: str) -> None:
    pin = validate(pin)
    row = _row(s)
    row.salt = secrets.token_hex(16)
    row.digest = _hash(pin, row.salt)
    row.fails, row.locked_until = 0, None
    s.add(row)
    s.commit()


def check(s: Session, pin: Optional[str]) -> str:
    """Devuelve 'ok', 'setup' (todavía no hay PIN), 'locked' (demasiados intentos) o 'bad'."""
    row, env = _row(s), env_pin()
    if not env and not row.digest:
        return "setup"
    if row.locked_until and row.locked_until > utcnow():
        return "locked"
    if not pin:  # sin PIN no se cuenta como intento fallido (p. ej. la primera carga de la página)
        return "bad"
    ok = (bool(env) and hmac.compare_digest(pin.encode(), env.encode())) or \
         (bool(row.digest) and _matches(pin, row.salt, row.digest))
    if ok and row.fails:
        row.fails = 0
        s.add(row)
        s.commit()
    elif not ok:
        row.fails += 1
        if row.fails >= MAX_FAILS:
            row.fails, row.locked_until = 0, utcnow() + LOCK
        s.add(row)
        s.commit()
    return "ok" if ok else "bad"
