import json
import os
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tatemono_map.api.database import SessionLocal, get_engine, init_db
from tatemono_map.api.schemas import BuildingCreate, BuildingRead, BuildingUpdate
from tatemono_map.models.building import Building

app = FastAPI(title="Tatemono Map")

def _db_status() -> str | None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        try:
            engine = get_engine()
            with engine.connect():
                return "ok"
        except Exception:
            return "error"

    try:
        engine = create_engine(database_url, pool_pre_ping=False)
        with engine.connect():
            return "ok"
    except Exception:
        return "error"


@app.get("/health")
def health():
    payload = {
        "status": "ok",
        "app": app.title,
        "time": datetime.now(timezone.utc).isoformat(),
    }

    db_status = _db_status()
    if db_status is not None:
        payload["db"] = db_status

    return payload


def get_db() -> Session:
    init_db()
    db = SessionLocal(bind=get_engine())
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def _ensure_building_summaries_table() -> None:
    engine = get_engine()
    ddl = """
    CREATE TABLE IF NOT EXISTS building_summaries (
        building_key TEXT PRIMARY KEY,
        name TEXT,
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
        lon REAL
    )
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))


@app.on_event("startup")
def _startup() -> None:
    _ensure_building_summaries_table()


def _parse_layout_types(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(loaded, list):
        return [str(item) for item in loaded]
    return []


def _summary_from_row(row: Any) -> dict[str, Any]:
    return {
        "building_key": row["building_key"],
        "name": row["name"],
        "address": row["address"],
        "vacancy_status": row["vacancy_status"],
        "listings_count": row["listings_count"],
        "layout_types": _parse_layout_types(row["layout_types_json"]),
        "rent_yen": {"min": row["rent_min"], "max": row["rent_max"]},
        "area_sqm": {"min": row["area_min"], "max": row["area_max"]},
        "move_in": {"min": row["move_in_min"], "max": row["move_in_max"]},
        "last_updated": row["last_updated"],
        "lat": row["lat"],
        "lon": row["lon"],
    }


@app.post("/buildings", response_model=BuildingRead, status_code=status.HTTP_201_CREATED)
def create_building(payload: BuildingCreate, db: DbSession):
    now = datetime.now(timezone.utc)
    building = Building(
        name=payload.name,
        address=payload.address,
        lat=payload.lat,
        lng=payload.lng,
        building_type=payload.building_type,
        floors=payload.floors,
        year_built=payload.year_built,
        source=payload.source,
        created_at=now,
        updated_at=now,
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


@app.get("/buildings")
def list_buildings(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    engine = get_engine()
    sql = """
        SELECT
            building_key,
            name,
            address,
            vacancy_status,
            listings_count,
            layout_types_json,
            rent_min,
            rent_max,
            area_min,
            area_max,
            move_in_min,
            move_in_max,
            last_updated,
            lat,
            lon
        FROM building_summaries
        ORDER BY last_updated DESC
        LIMIT :limit OFFSET :offset
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"limit": limit, "offset": offset}).mappings().all()
    return [_summary_from_row(row) for row in rows]


@app.get("/buildings/by-id/{building_id}", response_model=BuildingRead)
def get_building_by_id(building_id: int, db: DbSession):
    building = db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Building not found")
    return building


@app.get("/buildings/{building_key}")
def get_building_by_key(building_key: str):
    engine = get_engine()
    sql = """
        SELECT
            building_key,
            name,
            address,
            vacancy_status,
            listings_count,
            layout_types_json,
            rent_min,
            rent_max,
            area_min,
            area_max,
            move_in_min,
            move_in_max,
            last_updated,
            lat,
            lon
        FROM building_summaries
        WHERE building_key = :building_key
        LIMIT 1
    """
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"building_key": building_key}).mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return _summary_from_row(row)


@app.patch("/buildings/{building_id}", response_model=BuildingRead)
def update_building(building_id: int, payload: BuildingUpdate, db: DbSession):
    building = db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Building not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(building, key, value)
    building.updated_at = datetime.now(timezone.utc)
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


@app.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_building(building_id: int, db: DbSession):
    building = db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Building not found")
    db.delete(building)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return HTMLResponse('<h1>Tatemono Map</h1><p>Try <a href="/b/demo">/b/demo</a></p>')


@app.get("/b/{building_key}")
def building_page(building_key: str):
    if building_key == "demo":
        return {
            "building_key": building_key,
            "name": "デモ建物",
            "address": "福岡県北九州市小倉北区（デモ）",
            "vacancy_status": "空室あり",
            "listings_count": 2,
            "layout_types": ["1K", "1LDK"],
            "rent_yen": {"min": 52000, "max": 69000},
            "area_sqm": {"min": 22.5, "max": 31.2},
            "move_in": {"min": "要相談", "max": "要相談"},
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "lat": None,
            "lon": None,
        }
    return get_building_by_key(building_key)
