"""Acceso: sesiones por cookie, invitados y dueño. La identidad la da la cuenta de Google (ver google_integration).

OWNER_EMAIL (variable de entorno) es el dueño: siempre tiene acceso y administra a los invitados desde Ajustes.
"""
import hashlib
import os
import re
import secrets
from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from .db import AllowedEmail, LoginSession, User, utcnow

COOKIE = "session"
SESSION_DAYS = 30


def owner_email() -> str:
    return os.getenv("OWNER_EMAIL", "").strip().lower()


def normalize_email(email: Optional[str]) -> str:
    e = (email or "").strip().lower()
    if len(e) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
        raise ValueError("Ingresá un correo válido.")
    return e


def is_owner(email: str) -> bool:
    return bool(owner_email()) and email.strip().lower() == owner_email()


def is_allowed(s: Session, email: str) -> bool:
    e = email.strip().lower()
    return is_owner(e) or s.get(AllowedEmail, e) is not None


# ---------------------------------------------------------------- sesiones
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(s: Session, user_id: int) -> str:
    """Crea una sesión y devuelve el token (va en la cookie; en la BD queda solo su hash)."""
    for old in s.exec(select(LoginSession).where(LoginSession.user_id == user_id,
                                                 LoginSession.expires_at <= utcnow())).all():
        s.delete(old)  # limpia las vencidas de este usuario
    token = secrets.token_urlsafe(32)
    s.add(LoginSession(token_hash=_hash(token), user_id=user_id, expires_at=utcnow() + timedelta(days=SESSION_DAYS)))
    s.commit()
    return token


def user_for_token(s: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    ls = s.get(LoginSession, _hash(token))
    if not ls:
        return None
    if ls.expires_at <= utcnow():
        s.delete(ls)
        s.commit()
        return None
    return s.get(User, ls.user_id)


def end_session(s: Session, token: Optional[str]) -> None:
    ls = s.get(LoginSession, _hash(token)) if token else None
    if ls:
        s.delete(ls)
        s.commit()


def end_user_sessions(s: Session, user_id: int) -> None:
    for ls in s.exec(select(LoginSession).where(LoginSession.user_id == user_id)).all():
        s.delete(ls)
    s.commit()


# ---------------------------------------------------------------- invitados (los administra el dueño)
def list_invited(s: Session) -> list[dict]:
    users = {u.email: u for u in s.exec(select(User)).all()}
    out = []
    for a in s.exec(select(AllowedEmail).order_by(AllowedEmail.created_at)).all():
        u = users.get(a.email)
        out.append({"email": a.email, "nombre": u.name if u else "",
                    "ultimo_ingreso": u.last_login.isoformat() if u and u.last_login else None})
    return out


def invite(s: Session, email: Optional[str]) -> str:
    e = normalize_email(email)
    if is_owner(e):
        raise ValueError("Ese correo es el tuyo: ya tenés acceso.")
    if not s.get(AllowedEmail, e):
        s.add(AllowedEmail(email=e))
        s.commit()
    return e


def revoke(s: Session, email: Optional[str]) -> None:
    """Quita el acceso y cierra sus sesiones. Sus datos se conservan por si se lo vuelve a invitar."""
    e = normalize_email(email)
    a = s.get(AllowedEmail, e)
    if a:
        s.delete(a)
        s.commit()
    u = s.exec(select(User).where(User.email == e)).first()
    if u:
        end_user_sessions(s, u.id)
