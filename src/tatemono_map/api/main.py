import os
from datetime import datetime, timezone
from typing import Annotated
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tatemono_map.api.database import SessionLocal, get_engine, init_db
from tatemono_map.api.schemas import BuildingCreate, BuildingRead, BuildingUpdate
from tatemono_map.models.building import Building

app = FastAPI(title="Tatemono Map")

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "render" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

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


def _apply_search_filters(query, q: str | None, min_lat: float | None, max_lat: float | None,
                          min_lng: float | None, max_lng: float | None):
    if q:
        like_query = f"%{q}%"
        query = query.filter(
            (Building.name.ilike(like_query)) | (Building.address.ilike(like_query))
        )
    if min_lat is not None:
        query = query.filter(Building.lat >= min_lat)
    if max_lat is not None:
        query = query.filter(Building.lat <= max_lat)
    if min_lng is not None:
        query = query.filter(Building.lng >= min_lng)
    if max_lng is not None:
        query = query.filter(Building.lng <= max_lng)
    return query


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


@app.get("/buildings", response_model=list[BuildingRead])
def list_buildings(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: str | None = None,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lng: float | None = None,
    max_lng: float | None = None,
):
    query = db.query(Building)
    query = _apply_search_filters(query, q, min_lat, max_lat, min_lng, max_lng)
    query = query.order_by(Building.id).offset(offset).limit(limit)
    return query.all()


@app.get("/buildings/{building_id}", response_model=BuildingRead)
def get_building(building_id: int, db: DbSession):
    building = db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Building not found")
    return building


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

@app.get("/b/{building_key}", response_class=HTMLResponse)
def building_page(request: Request, building_key: str):
    # MVP：まずはスタブ。PoC完成後DBから取得に差し替える
    data = {
        "building_key": building_key,
        "building_name": "デモ建物",
        "address": "福岡県北九州市小倉北区（デモ）",
        "status": "空室あり",
        "rent_min": 52000,
        "rent_max": 69000,
        "area_min": 22.5,
        "area_max": 31.2,
        "layout_types": ["1K", "1LDK"],
        "available_from": "要相談",
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "line_url": "https://lin.ee/XXXXXXX"
    }
    return templates.TemplateResponse("building.html", {"request": request, **data})
