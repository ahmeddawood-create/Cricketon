import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool
import app.models  # Ensure all models are registered
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

def test_match_lifecycle_api(client):
    # 1. Create match
    match_payload = {
        "match_name": "Sunday Gully Cup",
        "venue": "Cross Road Ground",
        "overs_per_innings": 2,
        "players_per_side": 4,
        "team_a_name": "Warriors",
        "team_b_name": "Titans",
        "team_a_players": ["A1", "A2", "A3", "A4"],
        "team_b_players": ["B1", "B2", "B3", "B4"],
        "settings": {
            "last_man_standing": False,
            "wide_runs": 1,
            "no_ball_runs": 1,
            "wide_reball": True,
            "no_ball_reball": True,
        }
    }
    res = client.post("/api/matches", json=match_payload)
    assert res.status_code == 200
    match_data = res.json()
    match_id = match_data["id"]
    assert match_data["status"] == "created"

    # 2. Get players
    res = client.get(f"/api/matches/{match_id}/players")
    assert res.status_code == 200
    players_data = res.json()
    assert len(players_data["team_a"]["players"]) == 4
    assert len(players_data["team_b"]["players"]) == 4

    p_a1 = players_data["team_a"]["players"][0]["id"]
    p_a2 = players_data["team_a"]["players"][1]["id"]
    p_b1 = players_data["team_b"]["players"][0]["id"]

    # 3. Toss
    toss_payload = {
        "toss_winner_team": "Warriors",
        "toss_decision": "bat",
        "striker_name_or_id": str(p_a1),
        "non_striker_name_or_id": str(p_a2),
        "bowler_name_or_id": str(p_b1),
    }
    res = client.post(f"/api/matches/{match_id}/toss", json=toss_payload)
    assert res.status_code == 200
    toss_res = res.json()
    assert toss_res["batting_team"] == "Warriors"

    # 4. Score a 4 (boundary)
    ball_payload = {
        "batsman_runs": 4,
        "is_wicket": False,
    }
    res = client.post(f"/api/matches/{match_id}/ball", json=ball_payload)
    assert res.status_code == 200
    ball_res = res.json()
    assert ball_res["innings"]["total_runs"] == 4
    assert ball_res["innings"]["overs_str"] == "0.1"

    # 5. Undo the ball
    res = client.post(f"/api/matches/{match_id}/undo")
    assert res.status_code == 200
    undo_res = res.json()
    assert undo_res["innings"]["total_runs"] == 0
    assert undo_res["innings"]["overs_str"] == "0.0"

    # 6. Score again (1 run)
    res = client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 1})
    assert res.status_code == 200
    assert res.json()["innings"]["total_runs"] == 1

    # 7. Get scorecard
    res = client.get(f"/api/matches/{match_id}/scorecard")
    assert res.status_code == 200
    scorecard = res.json()
    assert scorecard["match_id"] == match_id
    assert len(scorecard["innings"]) == 1
    assert scorecard["innings"][0]["total_runs"] == 1
