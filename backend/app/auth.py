"""Acceso: sesiones por cookie, dueño y lista de bloqueo. La identidad la da la cuenta de Google (ver google_integration).

Acceso abierto: cualquier cuenta de Google puede entrar y usar la app, sin invitación previa. OWNER_EMAIL (variable
de entorno) es el dueño, que siempre tiene acceso y puede bloquear cuentas puntuales desde Ajustes.
"""
import hashlib
import os
import re
import secrets
from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from .db import BlockedEmail, LoginSession, User, utcnow

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


def is_blocked(s: Session, email: str) -> bool:
    return s.get(BlockedEmail, email.strip().lower()) is not None


def is_allowed(s: Session, email: str) -> bool:
    """Acceso abierto: entra cualquiera, salvo que el dueño lo haya bloqueado."""
    e = email.strip().lower()
    return is_owner(e) or not is_blocked(s, e)


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


# ---------------------------------------------------------------- bloqueo (lo administra el dueño)
def list_users(s: Session) -> list[dict]:
    """Todas las cuentas que ya entraron (menos el dueño), más los correos bloqueados que nunca llegaron a entrar."""
    blocked = {b.email for b in s.exec(select(BlockedEmail)).all()}
    users = [u for u in s.exec(select(User)).all() if not is_owner(u.email)]
    out = [{"email": u.email, "nombre": u.name, "foto": u.picture,
            "ultimo_ingreso": u.last_login.isoformat() if u.last_login else None,
            "bloqueado": u.email in blocked} for u in users]
    conocidos = {u.email for u in users}
    out += [{"email": e, "nombre": "", "foto": "", "ultimo_ingreso": None, "bloqueado": True}
            for e in blocked - conocidos]
    out.sort(key=lambda x: x["ultimo_ingreso"] or "", reverse=True)
    return out


def block(s: Session, email: Optional[str]) -> str:
    e = normalize_email(email)
    if is_owner(e):
        raise ValueError("No podés bloquearte a vos mismo.")
    if not s.get(BlockedEmail, e):
        s.add(BlockedEmail(email=e))
        s.commit()
    u = s.exec(select(User).where(User.email == e)).first()
    if u:
        end_user_sessions(s, u.id)  # corta el acceso ya mismo, no solo el próximo ingreso
    return e


def unblock(s: Session, email: Optional[str]) -> None:
    e = normalize_email(email)
    b = s.get(BlockedEmail, e)
    if b:
        s.delete(b)
        s.commit()
