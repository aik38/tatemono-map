from fastapi.testclient import TestClient


def _create_building(client: TestClient, **overrides):
    payload = {
        "name": "Sample Building",
        "address": "1-2-3 Example Street",
        "lat": 35.0,
        "lng": 139.0,
        "building_type": "office",
        "floors": 10,
        "year_built": 1999,
        "source": "manual",
    }
    payload.update(overrides)
    response = client.post("/buildings", json=payload)
    assert response.status_code == 201
    return response.json()


def _get_client(tmp_path, monkeypatch) -> TestClient:
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_path))

    from tatemono_map.api import database

    database.reset_engine()
    database.init_db()

    from tatemono_map.api.main import app

    return TestClient(app)


def test_create_and_get_building(tmp_path, monkeypatch):
    client = _get_client(tmp_path, monkeypatch)
    created = _create_building(client)

    response = client.get(f"/buildings/{created['id']}")
    assert response.status_code == 200
    data = response.json()

    assert data["name"] == "Sample Building"
    assert data["address"] == "1-2-3 Example Street"


def test_list_buildings_with_limit_offset(tmp_path, monkeypatch):
    client = _get_client(tmp_path, monkeypatch)
    first = _create_building(client, name="First", address="Alpha")
    second = _create_building(client, name="Second", address="Beta")
    _create_building(client, name="Third", address="Gamma")

    response = client.get("/buildings?limit=1&offset=1")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == second["id"]
    assert data[0]["name"] == second["name"]
    assert first["id"] != second["id"]


def test_search_buildings_by_query(tmp_path, monkeypatch):
    client = _get_client(tmp_path, monkeypatch)
    _create_building(client, name="Sakura Tower", address="Tokyo Central")
    _create_building(client, name="Ume House", address="Osaka")

    response = client.get("/buildings?q=Tokyo")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["name"] == "Sakura Tower"


def test_search_buildings_by_bbox(tmp_path, monkeypatch):
    client = _get_client(tmp_path, monkeypatch)
    in_box = _create_building(client, name="Inside", lat=35.5, lng=139.5)
    _create_building(client, name="Outside", lat=40.0, lng=140.0)

    response = client.get(
        "/buildings?min_lat=35.0&max_lat=36.0&min_lng=139.0&max_lng=140.0"
    )
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == in_box["id"]


def test_update_building(tmp_path, monkeypatch):
    client = _get_client(tmp_path, monkeypatch)
    created = _create_building(client, name="Old Name")

    response = client.patch(
        f"/buildings/{created['id']}",
        json={"name": "New Name", "floors": 12},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["name"] == "New Name"
    assert data["floors"] == 12
