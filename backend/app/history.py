"""Historial de la conversación con el asistente: se guarda por usuario, así es el mismo en cualquier dispositivo.

Solo se conservan los últimos MAX_MESSAGES mensajes de cada persona (los más viejos se van borrando) y cada uno
puede borrar su conversación completa desde la app.
"""
import json

from sqlmodel import Session, select

from .db import ChatMessage

MAX_MESSAGES = 100   # los que se guardan y se muestran
CONTEXT = 10         # los que se le envían al modelo como contexto


def recent(s: Session, uid: int, limit: int = MAX_MESSAGES) -> list[ChatMessage]:
    """Los últimos mensajes del usuario, del más viejo al más nuevo."""
    rows = s.exec(select(ChatMessage).where(ChatMessage.user_id == uid)
                  .order_by(ChatMessage.id.desc()).limit(limit)).all()
    return list(reversed(rows))


def context(s: Session, uid: int) -> list[dict]:
    """Formato que espera assistant.chat como historial."""
    return [{"role": m.role, "text": m.text} for m in recent(s, uid, CONTEXT)]


def as_output(m: ChatMessage) -> dict:
    return {"role": m.role, "text": m.text, "acciones": json.loads(m.actions_json) if m.actions_json else []}


def add_exchange(s: Session, uid: int, user_text: str, reply: str, acciones: list) -> None:
    """Guarda la pregunta y la respuesta, y descarta lo que exceda MAX_MESSAGES."""
    s.add(ChatMessage(user_id=uid, role="user", text=user_text))
    s.add(ChatMessage(user_id=uid, role="assistant", text=reply,
                      actions_json=json.dumps(acciones, ensure_ascii=False, default=str) if acciones else ""))
    s.commit()
    for old in s.exec(select(ChatMessage).where(ChatMessage.user_id == uid)
                      .order_by(ChatMessage.id.desc()).offset(MAX_MESSAGES)).all():
        s.delete(old)
    s.commit()


def clear(s: Session, uid: int) -> None:
    for m in s.exec(select(ChatMessage).where(ChatMessage.user_id == uid)).all():
        s.delete(m)
    s.commit()
