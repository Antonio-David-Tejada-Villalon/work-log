"""Conexión a la base de datos, modelos y configuración general."""
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


# ---------------------------------------------------------------- modelos
class Settings(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    daily_hours: float = 8.0            # horas de la jornada normal
    workdays_per_month: int = 22        # para expresar el banco en "meses laborales"
    count_deficit: bool = False         # si True, las horas faltantes restan del banco
    timezone: str = DEFAULT_TZ


class Shift(SQLModel, table=True):
    """Una jornada / tramo trabajado. Horas guardadas en UTC (sin tzinfo)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    start: datetime = Field(index=True, sa_type=DateTime)  # UTC sin tzinfo
    end: Optional[datetime] = Field(default=None, sa_type=DateTime)
    note: str = ""


class DayOverride(SQLModel, table=True):
    """Corrección manual de las horas extra de un día."""
    day: str = Field(primary_key=True)  # YYYY-MM-DD
    extra_seconds: int
    note: str = ""


class BankMovement(SQLModel, table=True):
    """Movimiento del banco de horas: negativo = horas usadas, positivo = ajuste a favor."""
    id: Optional[int] = Field(default=None, primary_key=True)
    day: str = Field(index=True)        # YYYY-MM-DD
    seconds: int
    kind: str = "uso"                   # uso | ajuste
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime)


class AppPin(SQLModel, table=True):
    """PIN de acceso creado desde la app (hash con sal) y contador de intentos fallidos."""
    id: int = Field(default=1, primary_key=True)
    salt: str = ""
    digest: str = ""                    # vacío = todavía no se creó el PIN
    fails: int = 0
    locked_until: Optional[datetime] = Field(default=None, sa_type=DateTime)  # UTC sin tzinfo


class GoogleToken(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    credentials_json: str = ""
    pending_state: str = ""
    pending_verifier: str = ""


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        if not s.get(Settings, 1):
            s.add(Settings(id=1))
            s.commit()


def get_session():
    with Session(engine) as s:
        yield s


def get_settings(s: Session) -> Settings:
    st = s.get(Settings, 1)
    if not st:
        st = Settings(id=1)
        s.add(st)
        s.commit()
        s.refresh(st)
    return st


__all__ = ["Settings", "Shift", "DayOverride", "BankMovement", "AppPin", "GoogleToken", "engine",
           "init_db", "get_session", "get_settings", "utcnow", "select", "Session"]
