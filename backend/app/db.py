"""Conexión a la base de datos, modelos y configuración general.

Multiusuario: cada persona entra con su cuenta de Google y todo lo demás (jornadas, banco, ajustes, conexión con
Google) pertenece a su usuario. Las tablas usan nombres propios (users, shifts, ...) para convivir con las de la
versión de un solo usuario (shift, settings, ...), que quedan intactas como respaldo.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import DateTime
from sqlmodel import Field, Session, SQLModel, create_engine, select


def _load_env() -> None:
    """Carga un archivo .env simple (clave=valor) sin dependencias extra."""
    root = Path(__file__).resolve().parents[2]
    env = next((p for p in (root / ".env", root / "backend" / ".env") if p.exists()), None)
    if not env:
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split(" #", 1)[0].strip()  # quita comentarios al final de la línea
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

DEFAULT_TZ = os.getenv("TIMEZONE", "America/Argentina/San_Juan")


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip() or "sqlite:///./data/horas.db"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("sqlite:///./"):
        Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    return url


ON_VERCEL = bool(os.getenv("VERCEL"))
if ON_VERCEL and not os.getenv("DATABASE_URL", "").strip():
    raise RuntimeError("En Vercel es obligatorio DATABASE_URL (Postgres de Supabase): el disco no es persistente.")

DB_URL = _db_url()
if DB_URL.startswith("sqlite"):
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:
    from sqlalchemy.pool import NullPool
    # Serverless + pooler de Supabase (modo transacción, puerto 6543): sin pool local
    # y sin sentencias preparadas (prepare_threshold=None), que el pooler no admite.
    engine = create_engine(DB_URL, poolclass=NullPool, pool_pre_ping=True,
                           connect_args={"prepare_threshold": None})


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- cuentas y acceso
class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)          # en minúsculas
    name: str = ""
    picture: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime)
    last_login: Optional[datetime] = Field(default=None, sa_type=DateTime)


class AllowedEmail(SQLModel, table=True):
    """Correos invitados por el dueño (OWNER_EMAIL). El dueño siempre tiene acceso."""
    __tablename__ = "allowed_emails"
    email: str = Field(primary_key=True)                 # en minúsculas
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime)


class LoginSession(SQLModel, table=True):
    """Sesión iniciada. Se guarda solo el hash del token que viaja en la cookie."""
    __tablename__ = "login_sessions"
    token_hash: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    expires_at: datetime = Field(sa_type=DateTime)


class OAuthState(SQLModel, table=True):
    """Estado y verificador PKCE de un inicio de sesión con Google en curso (dura minutos)."""
    __tablename__ = "oauth_states"
    state: str = Field(primary_key=True)
    verifier: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime)


# ---------------------------------------------------------------- datos de cada usuario
class Settings(SQLModel, table=True):
    __tablename__ = "user_settings"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    daily_hours: float = 8.0            # horas de la jornada normal
    workdays_per_month: int = 22        # para expresar el banco en "meses laborales"
    count_deficit: bool = False         # si True, las horas faltantes restan del banco
    timezone: str = DEFAULT_TZ


class Shift(SQLModel, table=True):
    """Una jornada / tramo trabajado. Horas guardadas en UTC (sin tzinfo)."""
    __tablename__ = "shifts"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    start: datetime = Field(index=True, sa_type=DateTime)  # UTC sin tzinfo
    end: Optional[datetime] = Field(default=None, sa_type=DateTime)
    note: str = ""


class DayOverride(SQLModel, table=True):
    """Corrección manual de las horas extra de un día."""
    __tablename__ = "day_overrides"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    day: str = Field(primary_key=True)  # YYYY-MM-DD
    extra_seconds: int
    note: str = ""


class BankMovement(SQLModel, table=True):
    """Movimiento del banco de horas: negativo = horas usadas, positivo = ajuste a favor."""
    __tablename__ = "bank_movements"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    day: str = Field(index=True)        # YYYY-MM-DD
    seconds: int
    kind: str = "uso"                   # uso | ajuste
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime)


class ChatMessage(SQLModel, table=True):
    """Conversación con el asistente: los últimos mensajes de cada usuario (ver history.py)."""
    __tablename__ = "chat_messages"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    role: str                           # user | assistant
    text: str
    actions_json: str = ""              # herramientas que usó el asistente en esa respuesta (JSON)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime)


class AiUsage(SQLModel, table=True):
    """Uso de la IA (Gemini) de cada usuario por día. El día es el del Pacífico de EE. UU., cuando Google reinicia las cuotas."""
    __tablename__ = "ai_usage"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    day: str = Field(primary_key=True)  # YYYY-MM-DD
    requests: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0


class GoogleToken(SQLModel, table=True):
    """Credenciales de Google Calendar y Tasks de cada usuario."""
    __tablename__ = "google_tokens"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    credentials_json: str = ""


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as s:
        yield s


def get_settings(s: Session, user_id: int) -> Settings:
    st = s.get(Settings, user_id)
    if not st:
        st = Settings(user_id=user_id)
        s.add(st)
        s.commit()
        s.refresh(st)
    return st


__all__ = ["User", "AllowedEmail", "LoginSession", "OAuthState", "Settings", "Shift", "DayOverride",
           "BankMovement", "ChatMessage", "AiUsage", "GoogleToken", "engine", "init_db", "get_session", "get_settings", "utcnow",
           "select", "Session", "ON_VERCEL"]
