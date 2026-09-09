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

def test_full_match_stress_simulation(client):
    # 1. Create a 2-over, 4-player match
    create_res = client.post("/api/matches", json={
        "match_name": "Full Stress Derby",
        "venue": "Highway Pitch",
        "overs_per_innings": 2,
        "players_per_side": 4,
        "team_a_name": "Kings",
        "team_b_name": "Royals",
        "team_a_players": ["K1", "K2", "K3", "K4"],
        "team_b_players": ["R1", "R2", "R3", "R4"],
        "settings": {
            "last_man_standing": False,
            "wide_runs": 1,
            "no_ball_runs": 1,
            "wide_reball": True,
            "no_ball_reball": True
        }
    })
    assert create_res.status_code == 200
    match_id = create_res.json()["id"]

    # 2. Get players
    players_res = client.get(f"/api/matches/{match_id}/players")
    p_data = players_res.json()
    k1 = p_data["team_a"]["players"][0]["id"]
    k2 = p_data["team_a"]["players"][1]["id"]
    k3 = p_data["team_a"]["players"][2]["id"]
    r1 = p_data["team_b"]["players"][0]["id"]
    r2 = p_data["team_b"]["players"][1]["id"]

    # 3. Toss
    toss_res = client.post(f"/api/matches/{match_id}/toss", json={
        "toss_winner_team": "Kings",
        "toss_decision": "bat",
        "striker_name_or_id": str(k1),
        "non_striker_name_or_id": str(k2),
        "bowler_name_or_id": str(r1)
    })
    assert toss_res.status_code == 200

    # 4. Over 1 Deliveries (Bowler: R1)
    # Ball 1: dot
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 0})
    # Ball 2: 4 runs
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 4})
    # Ball 3: wide (+1 extra run run, total 2)
    client.post(f"/api/matches/{match_id}/ball", json={"extra_type": "wide", "extra_runs": 1})
    # Ball 4: single (1 run, strike swaps)
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 1})
    # Ball 5: mistake tap (6 runs) -> immediate undo
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 6})
    undo_res = client.post(f"/api/matches/{match_id}/undo")
    assert undo_res.status_code == 200
    assert undo_res.json()["innings"]["total_runs"] == 7
    # Ball 5 re-bowl: dot
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 0})
    # Ball 6: 2 runs
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 2})
    # Ball 7 (legal 6): Wicket of striker
    b7_res = client.post(f"/api/matches/{match_id}/ball", json={
        "is_wicket": True,
        "dismissal_type": "bowled",
        "new_batsman_name_or_id": str(k3)
    })
    assert b7_res.status_code == 200
    assert b7_res.json()["status_info"]["over_ended"] is True
    assert b7_res.json()["status_info"]["needs_bowler"] is True

    # 5. Over 2: Select Bowler R2
    sel_res = client.post(f"/api/matches/{match_id}/select-bowler", json={"bowler_id": r2})
    assert sel_res.status_code == 200

    # Bowl remaining 6 balls of Over 2 to complete 1st innings
    for _ in range(6):
        client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 1})

    # Check match status -> should be innings_break
    live_res = client.get(f"/api/matches/{match_id}/live-summary")
    assert live_res.status_code == 200
    assert live_res.json()["status"] == "innings_break"
    target = live_res.json()["innings"]["target_runs"]
    assert target == 16

    # 6. Start 2nd Innings
    start_res = client.post(
        f"/api/matches/{match_id}/start-second-innings?striker_id={r1}&non_striker_id={r2}&bowler_id={k1}"
    )
    assert start_res.status_code == 200
    assert start_res.json()["target"] == target

    # 7. Chase the target
    # Score two consecutive sixes (12 runs)
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 6})
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 6})
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 6})

    # Verify match completed and winner is Royals
    scorecard_res = client.get(f"/api/matches/{match_id}/scorecard")
    assert scorecard_res.status_code == 200
    sc = scorecard_res.json()
    assert sc["status"] == "completed"
    assert "Royals" in sc["result"]
    assert len(sc["innings"]) == 2
