from fastapi.testclient import TestClient

from fieldhand.api import create_app
from fieldhand.world import World


def test_play_a_day_through_the_api(tmp_path):
    with TestClient(create_app(World(tmp_path / "api.db", day_seconds=60))) as client:
        r = client.post("/register", json={"name": "ana"})
        assert r.status_code == 200
        auth = {"Authorization": f"Bearer {r.json()['token']}"}

        assert client.get("/me").status_code == 401
        plot = client.post("/claim", json={}, headers=auth).json()["plot_id"]
        client.post("/harvest", json={"plot_id": plot}, headers=auth)
        client.post("/eat", json={"qty": 1}, headers=auth)
        r = client.post("/offers", json={"kind": "sell_rations", "price": 0.5}, headers=auth)
        assert r.status_code == 200

        me = client.get("/me", headers=auth).json()
        assert me["rations"] == 1
        assert me["eaten_today"] == 1
        assert 0 < me["seconds_left"] <= 60
        assert client.get("/offers").json()[0]["price"] == 0.5
        assert client.get("/ranking?by=life").json()[0]["name"] == "ana"


def test_errors_are_explained(tmp_path):
    with TestClient(create_app(World(tmp_path / "api.db", day_seconds=60))) as client:
        token = client.post("/register", json={"name": "ana"}).json()["token"]
        r = client.post(
            "/harvest", json={"plot_id": 1}, headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "that plot is not yours"
        assert client.post("/register", json={"name": "a"}).status_code == 400
