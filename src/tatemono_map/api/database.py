import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

_ENGINE = None
_DB_PATH: Path | None = None


def _resolve_db_path() -> Path:
    env_path = os.getenv("SQLITE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "tatemono_map.sqlite3"


def _get_database_url(db_path: Path) -> str:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{db_path.as_posix()}"


def get_engine():
    global _ENGINE
    global _DB_PATH

    db_path = _resolve_db_path()
    if _ENGINE is None or _DB_PATH != db_path:
        _DB_PATH = db_path
        _ENGINE = create_engine(
            _get_database_url(db_path),
            connect_args={"check_same_thread": False},
        )

    return _ENGINE


SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def init_db() -> None:
    from tatemono_map.models import building  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def reset_engine() -> None:
    global _ENGINE
    global _DB_PATH
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _DB_PATH = None
