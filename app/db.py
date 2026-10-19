import os
from functools import lru_cache

from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (registers tables)


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./local.db")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@lru_cache
def get_engine():
    url = database_url()
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Serverless + Supabase pooler (transaction mode): no client-side pool,
    # no prepared statements.
    return create_engine(url, poolclass=NullPool, connect_args={"prepare_threshold": None})


_ready = False


def init_db() -> None:
    global _ready
    if not _ready:
        SQLModel.metadata.create_all(get_engine())
        _ready = True


def reset_for_tests() -> None:
    global _ready
    _ready = False
    get_engine.cache_clear()


def get_session():
    init_db()
    with Session(get_engine()) as session:
        yield session
