import pytest
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.match import Match, MatchSettings, Innings
from app.models.player import Player, MatchPlayer
from app.models.ball_event import BallEvent, Wicket
from app.schemas.ball_schema import BallInput
from app.engine.state_machine import ScoringEngine
from app.engine.undo_manager import UndoManager
from app.services.scorecard_service import ScorecardService
from app.main import app
from app.db import get_session

@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s

def test_last_man_standing_full_lifecycle(session):
    # Setup 3 players per side match with Last Man Standing
    p1 = Player(name="Rohit")
    p2 = Player(name="Virat")
    p3 = Player(name="Surya")
    b1 = Player(name="Starc")
    b2 = Player(name="Cummins")
    session.add_all([p1, p2, p3, b1, b2])
    session.commit()

    match = Match(
        match_name="LMS Edge Test",
        overs_per_innings=2,
        players_per_side=3,
        team_a_name="India",
        team_b_name="Australia",
        status="in_progress",
    )
    session.add(match)
    session.commit()

    settings = MatchSettings(match_id=match.id, last_man_standing=True, wide_runs=1)
    session.add(settings)

    innings = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name="India",
        bowling_team_name="Australia",
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(innings)
    session.commit()
    match.current_innings_id = innings.id
    session.commit()

    engine = ScoringEngine(session)

    # 1. Wicket 1: Rohit out, Surya (p3) comes in
    engine.process_ball(
        match.id,
        BallInput(is_wicket=True, player_out_id=p1.id, new_batsman_name_or_id=str(p3.id))
    )
    session.refresh(innings)
    assert innings.total_wickets == 1
    assert innings.current_striker_id == p3.id
    assert innings.current_non_striker_id == p2.id

    # 2. Wicket 2: Virat (p2) out. No more bench players!
    engine.process_ball(
        match.id,
        BallInput(is_wicket=True, player_out_id=p2.id, new_batsman_name_or_id=None)
    )
    session.refresh(innings)
    assert innings.total_wickets == 2
    # In standard cricket this is all-out, but in LMS: Surya is Last Man Standing!
    assert innings.is_completed is False
    assert innings.current_striker_id == p3.id
    assert innings.current_non_striker_id is None

    # 3. Surya scores a single as lone batsman
    engine.process_ball(match.id, BallInput(batsman_runs=1))
    session.refresh(innings)
    assert innings.total_runs == 1
    # Strike remains with Surya (no crash, no swap to non-existent batsman)
    assert innings.current_striker_id == p3.id
    assert innings.current_non_striker_id is None

    # 4. Final wicket: Surya gets out -> now All Out (3 wickets == 3 players)
    engine.process_ball(match.id, BallInput(is_wicket=True, player_out_id=p3.id))
    session.refresh(innings)
    session.refresh(match)
    assert innings.total_wickets == 3
    assert innings.is_completed is True
    assert match.status == "innings_break"

def test_run_out_with_completed_runs(session):
    p1 = Player(name="P1")
    p2 = Player(name="P2")
    p3 = Player(name="P3")
    b1 = Player(name="Bowler")
    session.add_all([p1, p2, p3, b1])
    session.commit()

    match = Match(
        match_name="Run Out Test",
        overs_per_innings=2,
        players_per_side=4,
        team_a_name="A",
        team_b_name="B",
        status="in_progress",
    )
    session.add(match)
    session.commit()
    session.add(MatchSettings(match_id=match.id))

    innings = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name="A",
        bowling_team_name="B",
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(innings)
    session.commit()
    match.current_innings_id = innings.id
    session.commit()

    engine = ScoringEngine(session)

    # Batsmen run 1 run, but non-striker (p2) is run out attempting the 2nd run
    b_ev, status = engine.process_ball(
        match.id,
        BallInput(
            batsman_runs=1,
            is_wicket=True,
            dismissal_type="run_out",
            player_out_id=p2.id,
            new_batsman_name_or_id=str(p3.id),
        )
    )
    session.refresh(innings)

    # Completed run was scored
    assert innings.total_runs == 1
    assert innings.total_wickets == 1

    # Check scorecard: Bowler should NOT be credited with run-out wicket
    scorecard_svc = ScorecardService(session)
    inn_scorecard = scorecard_svc.get_innings_scorecard(innings)
    bowler_score = next(b for b in inn_scorecard.bowlers if b.player_id == b1.id)
    assert bowler_score.wickets == 0

def test_multi_ball_undo_across_overs(session):
    p1 = Player(name="Bat1")
    p2 = Player(name="Bat2")
    b1 = Player(name="Bowl1")
    b2 = Player(name="Bowl2")
    session.add_all([p1, p2, b1, b2])
    session.commit()

    match = Match(
        match_name="Undo Across Overs",
        overs_per_innings=2,
        players_per_side=4,
        team_a_name="A",
        team_b_name="B",
        status="in_progress",
    )
    session.add(match)
    session.commit()
    session.add(MatchSettings(match_id=match.id))

    innings = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name="A",
        bowling_team_name="B",
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(innings)
    session.commit()
    match.current_innings_id = innings.id
    session.commit()

    engine = ScoringEngine(session)
    undoer = UndoManager(session)

    # Bowl full 6 balls in Over 1 (1 run each ball)
    for _ in range(6):
        engine.process_ball(match.id, BallInput(batsman_runs=1))

    session.refresh(innings)
    assert innings.legal_balls == 6
    assert innings.total_runs == 6
    assert innings.current_bowler_id is None  # over complete

    # Select Bowler 2 for Over 2
    innings.current_bowler_id = b2.id
    session.commit()

    # Bowl Ball 1 of Over 2 (a 4)
    engine.process_ball(match.id, BallInput(batsman_runs=4))
    session.refresh(innings)
    assert innings.legal_balls == 7
    assert innings.total_runs == 10

    # NOW UNDO 3 TIMES IN A ROW!
    # Undo 1: Undoes ball 1 of Over 2 -> back to 6 balls, 6 runs
    undoer.undo_last_ball(match.id)
    session.refresh(innings)
    assert innings.legal_balls == 6
    assert innings.total_runs == 6

    # Undo 2: Undoes ball 6 of Over 1 -> back to 5 balls, 5 runs
    undoer.undo_last_ball(match.id)
    session.refresh(innings)
    assert innings.legal_balls == 5
    assert innings.total_runs == 5
    assert innings.current_bowler_id == b1.id

    # Undo 3: Undoes ball 5 of Over 1 -> back to 4 balls, 4 runs
    undoer.undo_last_ball(match.id)
    session.refresh(innings)
    assert innings.legal_balls == 4
    assert innings.total_runs == 4
    assert innings.current_bowler_id == b1.id

def test_tied_match_condition(session):
    p1 = Player(name="ChaseStriker")
    p2 = Player(name="ChaseNonStriker")
    b1 = Player(name="FinalBowler")
    session.add_all([p1, p2, b1])
    session.commit()

    match = Match(
        match_name="Tie Test",
        overs_per_innings=1,  # 1 over match (6 balls)
        players_per_side=3,
        team_a_name="BattingSide",
        team_b_name="DefendingSide",
        status="in_progress",
    )
    session.add(match)
    session.commit()
    session.add(MatchSettings(match_id=match.id))

    # 2nd Innings: Defending side made 10 runs in 1st inn, so target is 11
    innings2 = Innings(
        match_id=match.id,
        innings_number=2,
        batting_team_name="BattingSide",
        bowling_team_name="DefendingSide",
        target_runs=11,
        total_runs=0,
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(innings2)
    session.commit()
    match.current_innings_id = innings2.id
    session.commit()

    engine = ScoringEngine(session)

    # Balls 1-5: 2 runs each -> total 10 runs (1 run needed to win off the last ball)
    for _ in range(5):
        engine.process_ball(match.id, BallInput(batsman_runs=2))

    session.refresh(innings2)
    assert innings2.total_runs == 10
    assert innings2.legal_balls == 5

    # Ball 6 (final ball of match): Dot ball! (Overs completed, score is 10, target was 11)
    engine.process_ball(match.id, BallInput(batsman_runs=0))
    session.refresh(match)
    assert match.status == "completed"
    assert match.winner_team == "Tie"
    assert match.win_margin == "Match tied"

def test_chase_won_on_wide_extra(session):
    p1 = Player(name="S1")
    p2 = Player(name="S2")
    b1 = Player(name="B1")
    session.add_all([p1, p2, b1])
    session.commit()

    match = Match(
        match_name="Wide Win Test",
        overs_per_innings=2,
        players_per_side=3,
        status="in_progress",
    )
    session.add(match)
    session.commit()
    session.add(MatchSettings(match_id=match.id, wide_runs=1))

    innings = Innings(
        match_id=match.id,
        innings_number=2,
        batting_team_name="Chasers",
        bowling_team_name="Defenders",
        target_runs=5,
        total_runs=4,  # Need 1 to win
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(innings)
    session.commit()
    match.current_innings_id = innings.id
    session.commit()

    engine = ScoringEngine(session)

    # Bowler bowls a wide -> gives 1 extra run -> target 5 achieved!
    engine.process_ball(match.id, BallInput(extra_type="wide", extra_runs=0))
    session.refresh(match)
    assert match.status == "completed"
    assert match.winner_team == "Chasers"
    assert "wickets" in match.win_margin

def test_undo_across_innings_boundary(session):
    p1 = Player(name="P1")
    p2 = Player(name="P2")
    b1 = Player(name="B1")
    session.add_all([p1, p2, b1])
    session.commit()

    # 1 over match, 2 players per side (1 wicket = all out)
    match = Match(
        match_name="Innings Undo Test",
        overs_per_innings=1,
        players_per_side=2,
        status="in_progress",
    )
    session.add(match)
    session.commit()
    session.add(MatchSettings(match_id=match.id))

    inn1 = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name="Team1",
        bowling_team_name="Team2",
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(inn1)
    session.commit()
    match.current_innings_id = inn1.id
    session.commit()

    engine = ScoringEngine(session)
    undoer = UndoManager(session)

    # Ball 1: Wicket -> Innings 1 is all out (1 wicket out of 2 players)
    engine.process_ball(match.id, BallInput(is_wicket=True, player_out_id=p1.id))
    session.refresh(match)
    assert match.status == "innings_break"
    assert match.current_innings_id != inn1.id  # 2nd innings was created

    # Scorer realizes the wicket was wrongly called and UNDOES it!
    undoer.undo_last_ball(match.id)
    session.refresh(match)
    session.refresh(inn1)

    assert match.status == "in_progress"
    assert match.current_innings_id == inn1.id
    assert inn1.total_wickets == 0
    assert inn1.is_completed is False
    assert inn1.current_striker_id == p1.id
    assert inn1.current_non_striker_id == p2.id

def test_bowler_consecutive_over_restriction():
    client_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(client_engine)

    def get_test_session():
        with Session(client_engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    client = TestClient(app)

    # Create match
    m_res = client.post("/api/matches", json={
        "match_name": "Over Restrict Test",
        "overs_per_innings": 2,
        "team_a_name": "A",
        "team_b_name": "B",
        "team_a_players": ["A1", "A2"],
        "team_b_players": ["B1", "B2"]
    })
    match_id = m_res.json()["id"]

    # Toss
    t_res = client.post(f"/api/matches/{match_id}/toss", json={
        "toss_winner_team": "A",
        "toss_decision": "bat",
        "striker_name_or_id": "A1",
        "non_striker_name_or_id": "A2",
        "bowler_name_or_id": "B1"
    })
    b1_id = t_res.json()["bowler"]["id"]

    # Bowl 6 balls to finish over 1
    for _ in range(6):
        client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 0})

    # Try to pick B1 again without force -> should raise 400
    res = client.post(f"/api/matches/{match_id}/select-bowler", json={
        "bowler_id": b1_id,
        "force": False
    })
    assert res.status_code == 400
    assert "cannot bowl consecutive overs" in res.json()["detail"]

    # Try with force=True -> should succeed
    res = client.post(f"/api/matches/{match_id}/select-bowler", json={
        "bowler_id": b1_id,
        "force": True
    })
    assert res.status_code == 200

    app.dependency_overrides.clear()

def test_invalid_dismissal_on_no_ball_and_wide_rules(session):
    p1 = Player(name="Bat")
    p2 = Player(name="Runner")
    b1 = Player(name="Bowl")
    session.add_all([p1, p2, b1])
    session.commit()

    match = Match(match_name="Rules Test", overs_per_innings=1, players_per_side=3, status="in_progress")
    session.add(match)
    session.commit()
    session.add(MatchSettings(match_id=match.id))

    innings = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name="A",
        bowling_team_name="B",
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(innings)
    session.commit()
    match.current_innings_id = innings.id
    session.commit()

    engine = ScoringEngine(session)

    # 1. Caught on a No-Ball -> Must raise ValueError!
    with pytest.raises(ValueError, match="cannot be out 'caught' on a No Ball"):
        engine.process_ball(
            match.id,
            BallInput(is_wicket=True, dismissal_type="caught", extra_type="no_ball")
        )

    # 2. Bowled on a Wide -> Must raise ValueError!
    with pytest.raises(ValueError, match="cannot be out 'bowled' on a Wide"):
        engine.process_ball(
            match.id,
            BallInput(is_wicket=True, dismissal_type="bowled", extra_type="wide")
        )

    # 3. Stumped on a Wide -> VALID! Bowler gets credited wicket
    engine.process_ball(
        match.id,
        BallInput(is_wicket=True, dismissal_type="stumped", extra_type="wide", player_out_id=p1.id, new_batsman_name_or_id="NextBat")
    )
    session.refresh(innings)
    assert innings.total_runs == 1
    assert innings.total_wickets == 1
    assert innings.wide_runs == 1

    scorecard_svc = ScorecardService(session)
    inn_scorecard = scorecard_svc.get_innings_scorecard(innings)
    b_score = next(bw for bw in inn_scorecard.bowlers if bw.player_id == b1.id)
    assert b_score.wickets == 1  # stumped on wide is credited to bowler

def test_initial_scorecard_displays_openers_at_zero_balls(session):
    p1 = Player(name="OpenStriker")
    p2 = Player(name="OpenNonStriker")
    b1 = Player(name="OpenBowler")
    session.add_all([p1, p2, b1])
    session.commit()

    match = Match(match_name="Zero Ball Scorecard", overs_per_innings=1, players_per_side=3, status="in_progress")
    session.add(match)
    session.commit()
    session.add(MatchSettings(match_id=match.id))

    innings = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name="A",
        bowling_team_name="B",
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    session.add(innings)
    session.commit()
    match.current_innings_id = innings.id
    session.commit()

    # 0 balls bowled yet!
    scorecard_svc = ScorecardService(session)
    inn_scorecard = scorecard_svc.get_innings_scorecard(innings)

    # Assert both openers appear in the batsmen list with 0 runs, 0 balls
    assert len(inn_scorecard.batsmen) == 2
    striker = next(b for b in inn_scorecard.batsmen if b.is_striker)
    non_striker = next(b for b in inn_scorecard.batsmen if not b.is_striker)
    assert striker.player_id == p1.id
    assert striker.runs == 0
    assert striker.balls == 0
    assert striker.is_batting is True
    assert non_striker.player_id == p2.id
    assert non_striker.is_batting is True

    # Assert opening bowler appears in the bowlers list with 0 overs, 0 runs
    assert len(inn_scorecard.bowlers) == 1
    bowler = inn_scorecard.bowlers[0]
    assert bowler.player_id == b1.id
    assert bowler.overs_str == "0.0"
    assert bowler.is_bowling is True

def test_second_innings_batting_bowling_teams_swapped(session):
    client_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(client_engine)

    def get_test_session():
        with Session(client_engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    client = TestClient(app)

    # 1. Create match with Team Red and Team Blue
    m_res = client.post("/api/matches", json={
        "match_name": "Team Swap Verification",
        "overs_per_innings": 1,
        "players_per_side": 2,
        "team_a_name": "Team Red",
        "team_b_name": "Team Blue",
        "team_a_players": ["Red_1", "Red_2"],
        "team_b_players": ["Blue_1", "Blue_2"],
    })
    match_id = m_res.json()["id"]

    # 2. Toss: Team Red elects to BAT first
    t_res = client.post(f"/api/matches/{match_id}/toss", json={
        "toss_winner_team": "Team Red",
        "toss_decision": "bat",
        "striker_name_or_id": "Red_1",
        "non_striker_name_or_id": "Red_2",
        "bowler_name_or_id": "Blue_1",
    })
    assert t_res.json()["batting_team"] == "Team Red"
    assert t_res.json()["bowling_team"] == "Team Blue"

    # Verify 1st innings state
    live1 = client.get(f"/api/matches/{match_id}/live-summary").json()
    assert live1["innings"]["batting_team"] == "Team Red"
    assert live1["innings"]["bowling_team"] == "Team Blue"

    # 3. Bowl 1st innings (all out with 1 wicket out of 2 players)
    b_res = client.post(f"/api/matches/{match_id}/ball", json={
        "batsman_runs": 6,
        "is_wicket": True,
        "dismissal_type": "bowled",
    })
    assert b_res.json()["match_status"] == "innings_break"

    # 4. Check that 2nd innings has SWAPPED batting and bowling teams!
    live2 = client.get(f"/api/matches/{match_id}/live-summary").json()
    assert live2["status"] == "innings_break"
    assert live2["innings"]["innings_number"] == 2
    assert live2["innings"]["batting_team"] == "Team Blue"  # SWAPPED!
    assert live2["innings"]["bowling_team"] == "Team Red"   # SWAPPED!
    assert live2["innings"]["target_runs"] == 7

    # 5. Fetch players to get IDs for 2nd innings
    p_data = client.get(f"/api/matches/{match_id}/players").json()
    blue_1 = p_data["team_b"]["players"][0]["id"]
    blue_2 = p_data["team_b"]["players"][1]["id"]
    red_1 = p_data["team_a"]["players"][0]["id"]

    # 6. Start 2nd innings
    start_res = client.post(
        f"/api/matches/{match_id}/start-second-innings?striker_id={blue_1}&non_striker_id={blue_2}&bowler_id={red_1}"
    )
    assert start_res.status_code == 200
    assert start_res.json()["batting_team"] == "Team Blue"
    assert start_res.json()["bowling_team"] == "Team Red"

    # 7. Check full match scorecard reflects both innings with swapped teams
    sc_res = client.get(f"/api/matches/{match_id}/scorecard").json()
    assert len(sc_res["innings"]) == 2
    assert sc_res["innings"][0]["batting_team"] == "Team Red"
    assert sc_res["innings"][0]["bowling_team"] == "Team Blue"
    assert sc_res["innings"][1]["batting_team"] == "Team Blue"
    assert sc_res["innings"][1]["bowling_team"] == "Team Red"

    app.dependency_overrides.clear()


def test_custom_free_run_extras_config(session):
    """Test 0-run wide and 0-run no-ball custom match settings."""
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    # 1. Create match with 0-run wide and 0-run no-ball
    create_res = client.post("/api/matches", json={
        "match_name": "Zero Run Extras Match",
        "overs_per_innings": 2,
        "players_per_side": 4,
        "team_a_name": "Lions",
        "team_b_name": "Tigers",
        "settings": {
            "wide_runs": 0,
            "no_ball_runs": 0,
            "wide_reball": True,
            "no_ball_reball": True
        }
    })
    assert create_res.status_code == 200
    match_id = create_res.json()["id"]

    # 2. Record toss and confirm settings persist
    toss_res = client.post(f"/api/matches/{match_id}/toss", json={
        "toss_winner_team": "Lions",
        "toss_decision": "bat",
        "striker_name_or_id": "L1",
        "non_striker_name_or_id": "L2",
        "bowler_name_or_id": "T1",
        "settings": {
            "wide_runs": 0,
            "no_ball_runs": 0,
            "wide_reball": True,
            "no_ball_reball": True
        }
    })
    assert toss_res.status_code == 200

    # 3. Bowl a Wide ball with 0 extra runs
    w1_res = client.post(f"/api/matches/{match_id}/ball", json={
        "batsman_runs": 0,
        "extra_type": "wide",
        "extra_runs": 0,
        "is_wicket": False
    })
    assert w1_res.status_code == 200
    summary1 = client.get(f"/api/matches/{match_id}/live-summary").json()
    # Should have 0 runs, 0 legal balls
    assert summary1["innings"]["total_runs"] == 0
    assert summary1["innings"]["overs_str"] == "0.0"

    # 4. Bowl a Wide ball where batsmen physically ran 1 run (extra_runs = 1)
    w2_res = client.post(f"/api/matches/{match_id}/ball", json={
        "batsman_runs": 0,
        "extra_type": "wide",
        "extra_runs": 1,
        "is_wicket": False
    })
    assert w2_res.status_code == 200
    summary2 = client.get(f"/api/matches/{match_id}/live-summary").json()
    # Total runs should be 1 (0 base + 1 ran)
    assert summary2["innings"]["total_runs"] == 1
    assert summary2["innings"]["overs_str"] == "0.0"

    # 5. Bowl a No-Ball with 4 runs off the bat (no free penalty run)
    nb_res = client.post(f"/api/matches/{match_id}/ball", json={
        "batsman_runs": 4,
        "extra_type": "no_ball",
        "extra_runs": 0,
        "is_wicket": False
    })
    assert nb_res.status_code == 200
    summary3 = client.get(f"/api/matches/{match_id}/live-summary").json()
    # Total runs: 1 + 4 = 5. Overs still 0.0
    assert summary3["innings"]["total_runs"] == 5
    assert summary3["innings"]["overs_str"] == "0.0"

    # 6. Undo the No-Ball
    undo_res = client.post(f"/api/matches/{match_id}/undo")
    assert undo_res.status_code == 200
    summary4 = client.get(f"/api/matches/{match_id}/live-summary").json()
    assert summary4["innings"]["total_runs"] == 1
    assert summary4["innings"]["overs_str"] == "0.0"

    # 7. Bowl a legal 6
    legal_res = client.post(f"/api/matches/{match_id}/ball", json={
        "batsman_runs": 6,
        "extra_type": None,
        "extra_runs": 0,
        "is_wicket": False
    })
    assert legal_res.status_code == 200
    summary5 = client.get(f"/api/matches/{match_id}/live-summary").json()
    assert summary5["innings"]["total_runs"] == 7
    assert summary5["innings"]["overs_str"] == "0.1"

    app.dependency_overrides.clear()


def test_ongoing_match_bowler_figures_and_last_over_tracking(session):
    """Test ongoing match bowler figures and last_over_bowler_id tracking across overs."""
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    # 1. Create match
    create_res = client.post("/api/matches", json={
        "match_name": "Bowler Figures Test",
        "overs_per_innings": 5,
        "players_per_side": 4,
        "team_a_name": "Warriors",
        "team_b_name": "Titans",
        "team_a_players": ["W1", "W2", "W3", "W4"],
        "team_b_players": ["Bumrah", "Shami", "Siraj", "Kuldeep"],
    })
    assert create_res.status_code == 200
    match_id = create_res.json()["id"]

    # 2. Get player IDs
    players_data = client.get(f"/api/matches/{match_id}/players").json()
    striker_id = players_data["team_a"]["players"][0]["id"]
    non_striker_id = players_data["team_a"]["players"][1]["id"]
    bumrah_id = players_data["team_b"]["players"][0]["id"]
    shami_id = players_data["team_b"]["players"][1]["id"]

    # 3. Toss
    toss_res = client.post(f"/api/matches/{match_id}/toss", json={
        "toss_winner_team": "Warriors",
        "toss_decision": "bat",
        "striker_name_or_id": str(striker_id),
        "non_striker_name_or_id": str(non_striker_id),
        "bowler_name_or_id": str(bumrah_id),
    })
    assert toss_res.status_code == 200

    # 4. Bumrah bowls an over: 1 wide, 5 singles, 1 wicket on the 6th legal ball
    # Ball 1 (Wide): 1 extra run
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 0, "extra_type": "wide", "extra_runs": 0})
    # Balls 2-6 (legal): singles
    for _ in range(5):
        client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 1})
    # Ball 7 (6th legal ball): wicket!
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 0, "is_wicket": True, "dismissal_type": "bowled", "player_out_id": striker_id, "new_batsman_name_or_id": "W3"})

    # 5. Over is complete! Check live summary
    summary = client.get(f"/api/matches/{match_id}/live-summary").json()
    innings = summary["innings"]
    assert innings["overs_str"] == "1.0"
    assert innings["last_over_bowler_id"] == bumrah_id

    # Check Bumrah's ongoing match figures
    bumrah_stats = next(b for b in innings["bowlers"] if b["player_id"] == bumrah_id)
    assert bumrah_stats["overs_str"] == "1.0"
    assert bumrah_stats["legal_balls"] == 6
    # 1 wide run + 5 singles = 6 runs conceded
    assert bumrah_stats["runs_conceded"] == 6
    assert bumrah_stats["wickets"] == 1
    assert bumrah_stats["wides"] == 1
    assert bumrah_stats["economy"] == 6.0

    # 6. Verify consecutive over restriction
    # Selecting Bumrah again without force should fail
    fail_res = client.post(f"/api/matches/{match_id}/select-bowler", json={"bowler_id": bumrah_id, "force": False})
    assert fail_res.status_code == 400
    assert "bowled the previous over" in fail_res.json()["detail"]

    # Selecting Shami should succeed
    shami_res = client.post(f"/api/matches/{match_id}/select-bowler", json={"bowler_id": shami_id, "force": False})
    assert shami_res.status_code == 200

    # Selecting Bumrah with force=True (Gully override) should succeed
    force_res = client.post(f"/api/matches/{match_id}/select-bowler", json={"bowler_id": bumrah_id, "force": True})
    assert force_res.status_code == 200

    app.dependency_overrides.clear()


def test_delete_and_reset_matches_and_players(session):
    """Test delete and reset operations for matches, players, and bulk cleanups."""
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    # 1. Create match
    create_res = client.post("/api/matches", json={
        "match_name": "Match to Delete",
        "overs_per_innings": 2,
        "players_per_side": 3,
        "team_a_name": "Eagles",
        "team_b_name": "Hawks",
        "team_a_players": ["E1", "E2", "E3"],
        "team_b_players": ["H1", "H2", "H3"],
    })
    assert create_res.status_code == 200
    match_id = create_res.json()["id"]

    # 2. Conduct toss
    client.post(f"/api/matches/{match_id}/toss", json={
        "toss_winner_team": "Eagles",
        "toss_decision": "bat",
        "striker_name_or_id": "E1",
        "non_striker_name_or_id": "E2",
        "bowler_name_or_id": "H1",
    })

    # 3. Bowl 2 balls
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 4})
    client.post(f"/api/matches/{match_id}/ball", json={"batsman_runs": 1})

    summary_before = client.get(f"/api/matches/{match_id}/live-summary").json()
    assert summary_before["innings"]["total_runs"] == 5

    # 4. Test Match Reset
    reset_res = client.post(f"/api/matches/{match_id}/reset")
    assert reset_res.status_code == 200
    summary_after_reset = client.get(f"/api/matches/{match_id}/live-summary").json()
    assert summary_after_reset["status"] == "created"
    assert "innings" not in summary_after_reset or summary_after_reset.get("innings") is None

    # 5. Test Match Deletion
    del_res = client.delete(f"/api/matches/{match_id}")
    assert del_res.status_code == 200
    assert "deleted successfully" in del_res.json()["message"]

    # Verify match is gone
    get_res = client.get(f"/api/matches/{match_id}/scorecard")
    assert get_res.status_code == 404

    # 6. Test Player creation and deletion
    new_p = Player(name="GhostPlayer")
    session.add(new_p)
    session.commit()
    p_id = new_p.id

    # Delete unused player
    del_p_res = client.delete(f"/api/players/{p_id}")
    assert del_p_res.status_code == 200
    assert session.get(Player, p_id) is None

    # 7. Test Bulk Cleanup Unused Players
    p_unused1 = Player(name="UnusedOne")
    p_unused2 = Player(name="UnusedTwo")
    session.add_all([p_unused1, p_unused2])
    session.commit()

    # 8. Test Player deletion restriction when player has played
    p_active = Player(name="ActivePlayer")
    session.add(p_active)
    session.commit()

    # Create a dummy match and ball with p_active
    m_active = Match(match_name="Active Match", overs_per_innings=1, players_per_side=2, team_a_name="A", team_b_name="B")
    session.add(m_active)
    session.commit()
    inn_active = Innings(match_id=m_active.id, innings_number=1, batting_team_name="A", bowling_team_name="B")
    session.add(inn_active)
    session.commit()
    b_active = BallEvent(innings_id=inn_active.id, over_number=0, ball_in_over=1, striker_id=p_active.id, bowler_id=p_active.id, batsman_runs=1)
    session.add(b_active)
    session.commit()

    # Attempt delete without force - should fail
    active_del_fail = client.delete(f"/api/players/{p_active.id}")
    assert active_del_fail.status_code == 400
    assert "recorded deliveries" in active_del_fail.json()["detail"]

    # Attempt delete with force=true - should succeed
    active_del_ok = client.delete(f"/api/players/{p_active.id}?force=true")
    assert active_del_ok.status_code == 200
    assert session.get(Player, p_active.id) is None

    # 9. Test Bulk Match Deletion
    bulk_del_res = client.delete("/api/matches?status=all")
    assert bulk_del_res.status_code == 200
    assert "Deleted" in bulk_del_res.json()["message"]

    app.dependency_overrides.clear()


def test_compulsory_next_batter_on_wicket(session):
    """Verify that selecting the next batter is compulsory on a wicket unless all-out."""
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    # 1. Create a match with 4 players per side (3 wickets for all out)
    res = client.post("/api/matches", json={
        "match_name": "Compulsory Next Batter Cup",
        "overs_per_innings": 2,
        "players_per_side": 4,
        "team_a_name": "Panthers",
        "team_b_name": "Leopards",
        "team_a_players": ["Panther1", "Panther2", "Panther3", "Panther4"],
        "team_b_players": ["Leo1", "Leo2", "Leo3", "Leo4"],
    })
    assert res.status_code == 200
    match_id = res.json()["id"]

    # 2. Get players
    p_data = client.get(f"/api/matches/{match_id}/players").json()
    p1 = p_data["team_a"]["players"][0]["id"]
    p2 = p_data["team_a"]["players"][1]["id"]
    p3 = p_data["team_a"]["players"][2]["id"]
    b1 = p_data["team_b"]["players"][0]["id"]

    # 3. Toss
    client.post(f"/api/matches/{match_id}/toss", json={
        "toss_winner_team": "Panthers",
        "toss_decision": "bat",
        "striker_name_or_id": str(p1),
        "non_striker_name_or_id": str(p2),
        "bowler_name_or_id": str(b1),
    })

    # 4. Attempt to record a wicket WITHOUT incoming batsman -> Must fail with 400!
    fail_w1 = client.post(f"/api/matches/{match_id}/ball", json={
        "is_wicket": True,
        "dismissal_type": "bowled",
        "player_out_id": p1,
        "new_batsman_name_or_id": None
    })
    assert fail_w1.status_code == 400
    assert "Selecting the next batter is compulsory" in fail_w1.json()["detail"]

    # Also fail if empty string is passed
    fail_w2 = client.post(f"/api/matches/{match_id}/ball", json={
        "is_wicket": True,
        "dismissal_type": "bowled",
        "player_out_id": p1,
        "new_batsman_name_or_id": "   "
    })
    assert fail_w2.status_code == 400
    assert "Selecting the next batter is compulsory" in fail_w2.json()["detail"]

    # 5. Record wicket WITH incoming batsman p3 -> Must succeed!
    ok_w1 = client.post(f"/api/matches/{match_id}/ball", json={
        "is_wicket": True,
        "dismissal_type": "bowled",
        "player_out_id": p1,
        "new_batsman_name_or_id": str(p3)
    })
    assert ok_w1.status_code == 200
    live_after_w1 = client.get(f"/api/matches/{match_id}/live-summary").json()
    assert live_after_w1["innings"]["total_wickets"] == 1
    # Check that p3 is now the striker
    striker = next(b for b in live_after_w1["innings"]["batsmen"] if b["is_striker"])
    assert striker["player_id"] == p3

    # 6. Test select-batsman endpoint
    sel_res = client.post(f"/api/matches/{match_id}/select-batsman", json={
        "batsman_name_or_id": "SurpriseSub",
        "is_striker": False
    })
    assert sel_res.status_code == 200
    assert "SurpriseSub" in sel_res.json()["message"]

    # 7. Record 2nd wicket with Panther4 coming in
    ok_w2 = client.post(f"/api/matches/{match_id}/ball", json={
        "is_wicket": True,
        "dismissal_type": "caught",
        "player_out_id": p2,
        "new_batsman_name_or_id": "Panther4"
    })
    assert ok_w2.status_code == 200

    # 8. Record 3rd wicket (All Out: 3 wickets for 4 players) -> new_batsman_name_or_id NOT required!
    ok_w3 = client.post(f"/api/matches/{match_id}/ball", json={
        "is_wicket": True,
        "dismissal_type": "bowled",
        "new_batsman_name_or_id": None
    })
    assert ok_w3.status_code == 200
    assert ok_w3.json()["match_status"] == "innings_break"

    app.dependency_overrides.clear()




