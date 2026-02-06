import os
import re
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

ROOM_PREFIX_PATTERN = re.compile(r"^\s*\d{1,4}\s*[:：]\s*")

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
    ensure_building_summaries_table(engine)


def ensure_building_summaries_table(engine=None) -> None:
    if engine is None:
        engine = get_engine()
    ddl = """
    CREATE TABLE IF NOT EXISTS building_summaries (
        building_key TEXT PRIMARY KEY,
        name TEXT,
        raw_name TEXT,
        address TEXT,
        vacancy_status TEXT,
        listings_count INTEGER,
        layout_types_json TEXT,
        rent_min INTEGER,
        rent_max INTEGER,
        area_min REAL,
        area_max REAL,
        move_in_min TEXT,
        move_in_max TEXT,
        last_updated TEXT,
        lat REAL,
        lon REAL,
        rent_yen_min INTEGER,
        rent_yen_max INTEGER,
        area_sqm_min REAL,
        area_sqm_max REAL
    )
    """
    required_columns = {
        "name": "TEXT",
        "raw_name": "TEXT",
        "address": "TEXT",
        "vacancy_status": "TEXT",
        "listings_count": "INTEGER",
        "layout_types_json": "TEXT",
        "rent_min": "INTEGER",
        "rent_max": "INTEGER",
        "area_min": "REAL",
        "area_max": "REAL",
        "move_in_min": "TEXT",
        "move_in_max": "TEXT",
        "last_updated": "TEXT",
        "lat": "REAL",
        "lon": "REAL",
    }
    legacy_columns = {
        "rent_yen_min": "INTEGER",
        "rent_yen_max": "INTEGER",
        "area_sqm_min": "REAL",
        "area_sqm_max": "REAL",
    }
    with engine.begin() as conn:
        conn.execute(text(ddl))
        existing_columns = {
            row["name"] for row in conn.execute(text("PRAGMA table_info(building_summaries)")).mappings()
        }
        for column, column_type in (required_columns | legacy_columns).items():
            if column not in existing_columns:
                conn.execute(
                    text(f"ALTER TABLE building_summaries ADD COLUMN {column} {column_type}")
                )

        conn.execute(
            text(
                """
                UPDATE building_summaries
                SET raw_name = COALESCE(raw_name, name)
                WHERE name IS NOT NULL
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE building_summaries
                SET name = TRIM(
                    CASE
                        WHEN name GLOB '[0-9]:*' THEN SUBSTR(name, INSTR(name, ':') + 1)
                        WHEN name GLOB '[0-9][0-9]:*' THEN SUBSTR(name, INSTR(name, ':') + 1)
                        WHEN name GLOB '[0-9][0-9][0-9]:*' THEN SUBSTR(name, INSTR(name, ':') + 1)
                        WHEN name GLOB '[0-9][0-9][0-9][0-9]:*' THEN SUBSTR(name, INSTR(name, ':') + 1)
                        WHEN name GLOB '[0-9]：*' THEN SUBSTR(name, INSTR(name, '：') + 1)
                        WHEN name GLOB '[0-9][0-9]：*' THEN SUBSTR(name, INSTR(name, '：') + 1)
                        WHEN name GLOB '[0-9][0-9][0-9]：*' THEN SUBSTR(name, INSTR(name, '：') + 1)
                        WHEN name GLOB '[0-9][0-9][0-9][0-9]：*' THEN SUBSTR(name, INSTR(name, '：') + 1)
                        ELSE name
                    END
                )
                WHERE name IS NOT NULL
                """
            )
        )
        rows = conn.execute(
            text("SELECT building_key, name FROM building_summaries WHERE name IS NOT NULL")
        ).mappings().all()
        for row in rows:
            normalized = ROOM_PREFIX_PATTERN.sub("", str(row["name"]).strip()).strip()
            if normalized != row["name"]:
                conn.execute(
                    text(
                        "UPDATE building_summaries SET name = :name WHERE building_key = :building_key"
                    ),
                    {"building_key": row["building_key"], "name": normalized},
                )
        if legacy_columns.keys() & existing_columns:
            conn.execute(
                text(
                    """
                    UPDATE building_summaries
                    SET
                        rent_min = COALESCE(rent_min, rent_yen_min),
                        rent_max = COALESCE(rent_max, rent_yen_max),
                        area_min = COALESCE(area_min, area_sqm_min),
                        area_max = COALESCE(area_max, area_sqm_max)
                    """
                )
            )


def reset_engine() -> None:
    global _ENGINE
    global _DB_PATH
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _DB_PATH = None
