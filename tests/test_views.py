import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool
import app.models
from app.main import app
from app.db import get_session

@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

def test_view_routes(client):
    # Test dashboard route
    res = client.get("/")
    assert res.status_code == 200
    assert "MyCric" in res.text

    # Test players directory route
    res = client.get("/players")
    assert res.status_code == 200
    assert "Player Career Records" in res.text

    # Create a match to test match-specific views
    m_res = client.post("/api/matches", json={
        "match_name": "Test Cup",
        "team_a_name": "Team 1",
        "team_b_name": "Team 2",
        "team_a_players": ["P1", "P2"],
        "team_b_players": ["P3", "P4"]
    })
    match_id = m_res.json()["id"]

    # Toss view
    res = client.get(f"/match/{match_id}/toss")
    assert res.status_code == 200
    assert "Coin Toss" in res.text

    # Scorer view
    res = client.get(f"/match/{match_id}/score")
    assert res.status_code == 200
    assert "Live Scorer" in res.text

    # Live spectator view
    res = client.get(f"/match/{match_id}/live")
    assert res.status_code == 200
    assert "LIVE SPECTATOR" in res.text

    # Scorecard view
    res = client.get(f"/match/{match_id}/scorecard")
    assert res.status_code == 200
    assert "Scorecard" in res.text
