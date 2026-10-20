import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from fieldhand import config, github
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
        assert client.post("/register", json={"name": "a b"}).status_code == 400


def test_sign_in_with_github(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_CLIENT_ID", "client-id")
    users = {
        "ana": {"id": 1, "login": "ana", "created_at": "2015-01-01T00:00:00Z"},
        "new": {"id": 2, "login": "new", "created_at": datetime.now(UTC).isoformat()},
    }
    monkeypatch.setattr(github, "fetch_user", lambda code: users[code])

    with TestClient(create_app(World(tmp_path / "api.db", day_seconds=60))) as client:

        def sign_in(code):
            r = client.get("/login", follow_redirects=False)
            assert r.status_code == 307
            state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
            return client.get(f"/auth/github?code={code}&state={state}")

        assert client.get("/world").json()["signup"] == "github"
        assert client.post("/register", json={"name": "bob"}).status_code == 403

        first = sign_in("ana")
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        token = re.search(r"<pre>([\w-]+)</pre>", first.text).group(1)
        me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["name"] == "ana"

        # Signing in again gives the same player and token.
        assert token in sign_in("ana").text
        assert client.get("/world").json()["players"] == 1

        assert sign_in("new").status_code == 403
        assert client.get("/auth/github?code=ana&state=forged").status_code == 400
