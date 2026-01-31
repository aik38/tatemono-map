import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine

app = FastAPI(title="Tatemono Map")

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "render" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def _db_status() -> str | None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None

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
