from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_parent_dir(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    path_part = url.removeprefix("sqlite:///")
    if path_part in (":memory:", "/:memory:"):
        return
    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = Path(__file__).resolve().parent / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def create_engine_from_settings() -> Engine:
    settings = get_settings()
    url = settings.database_url
    _ensure_sqlite_parent_dir(url)
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args or {})


engine = create_engine_from_settings()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
