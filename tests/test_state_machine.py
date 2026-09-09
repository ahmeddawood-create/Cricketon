import pytest
from sqlmodel import SQLModel, create_engine, Session
from app.models.match import Match, MatchSettings, Innings
from app.models.player import Player, MatchPlayer
from app.models.ball_event import BallEvent, Wicket
from app.schemas.ball_schema import BallInput
from app.engine.state_machine import ScoringEngine
from app.engine.undo_manager import UndoManager
from app.services.scorecard_service import ScorecardService

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture
def setup_match(db_session):
    # Create players
    p1 = Player(name="Rohit")  # Striker
    p2 = Player(name="Virat")  # Non-striker
    p3 = Player(name="Rahul")  # Incoming batsman
    b1 = Player(name="Starc")  # Bowler 1
    b2 = Player(name="Cummins") # Bowler 2
    db_session.add_all([p1, p2, p3, b1, b2])
    db_session.commit()

    # Create match
    match = Match(
        match_name="Gully Derby",
        overs_per_innings=2,
        players_per_side=3,
        team_a_name="India",
        team_b_name="Australia",
        status="in_progress",
    )
    db_session.add(match)
    db_session.commit()

    settings = MatchSettings(match_id=match.id, wide_runs=1, no_ball_runs=1)
    db_session.add(settings)

    # 1st Innings
    innings = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name="India",
        bowling_team_name="Australia",
        current_striker_id=p1.id,
        current_non_striker_id=p2.id,
        current_bowler_id=b1.id,
    )
    db_session.add(innings)
    db_session.commit()

    match.current_innings_id = innings.id
    db_session.commit()

    return {
        "match": match,
        "innings": innings,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "b1": b1,
        "b2": b2,
    }

def test_strike_rotation_on_runs(db_session, setup_match):
    engine = ScoringEngine(db_session)
    data = setup_match
    match = data["match"]
    p1, p2 = data["p1"], data["p2"]

    # Ball 1: 1 run scored -> strike should rotate (p2 striker, p1 non-striker)
    b1, s1 = engine.process_ball(match.id, BallInput(batsman_runs=1))
    db_session.refresh(data["innings"])
    assert data["innings"].current_striker_id == p2.id
    assert data["innings"].current_non_striker_id == p1.id
    assert data["innings"].total_runs == 1
    assert data["innings"].legal_balls == 1

    # Ball 2: 2 runs scored -> strike should NOT rotate (p2 stays striker)
    b2, s2 = engine.process_ball(match.id, BallInput(batsman_runs=2))
    db_session.refresh(data["innings"])
    assert data["innings"].current_striker_id == p2.id
    assert data["innings"].current_non_striker_id == p1.id
    assert data["innings"].total_runs == 3
    assert data["innings"].legal_balls == 2

    # Ball 3: 4 runs (boundary) -> strike stays with p2
    b3, s3 = engine.process_ball(match.id, BallInput(batsman_runs=4))
    db_session.refresh(data["innings"])
    assert data["innings"].current_striker_id == p2.id
    assert data["innings"].total_runs == 7

def test_over_completion_and_strike_swap(db_session, setup_match):
    engine = ScoringEngine(db_session)
    data = setup_match
    match = data["match"]
    innings = data["innings"]
    p1, p2 = data["p1"], data["p2"]

    # Bowl 5 dot balls (p1 striker)
    for _ in range(5):
        engine.process_ball(match.id, BallInput(batsman_runs=0))

    db_session.refresh(innings)
    assert innings.legal_balls == 5
    assert innings.current_striker_id == p1.id
    assert innings.current_bowler_id == data["b1"].id

    # Ball 6: dot ball, ends over.
    # At over end, strike swaps ends for the new over: p2 becomes striker!
    # current_bowler_id becomes None to prompt for new bowler.
    b6, s6 = engine.process_ball(match.id, BallInput(batsman_runs=0))
    db_session.refresh(innings)
    assert innings.legal_balls == 6
    assert s6["over_ended"] is True
    assert s6["needs_bowler"] is True
    assert innings.current_striker_id == p2.id
    assert innings.current_non_striker_id == p1.id
    assert innings.current_bowler_id is None

def test_extras_and_reball(db_session, setup_match):
    engine = ScoringEngine(db_session)
    data = setup_match
    match = data["match"]
    innings = data["innings"]

    # Wide ball (+0 extra runs, so total 1 run, not legal delivery)
    engine.process_ball(match.id, BallInput(extra_type="wide", extra_runs=0))
    db_session.refresh(innings)
    assert innings.total_runs == 1
    assert innings.wide_runs == 1
    assert innings.legal_balls == 0  # didn't increment legal balls

    # No ball with 2 runs off bat
    engine.process_ball(match.id, BallInput(batsman_runs=2, extra_type="no_ball", extra_runs=0))
    db_session.refresh(innings)
    # Total runs: 1 (previous) + 1 (nb penalty) + 2 (bat) = 4
    assert innings.total_runs == 4
    assert innings.no_ball_runs == 1
    assert innings.legal_balls == 0

def test_wicket_and_undo(db_session, setup_match):
    engine = ScoringEngine(db_session)
    undoer = UndoManager(db_session)
    data = setup_match
    match = data["match"]
    innings = data["innings"]
    p1, p2, p3 = data["p1"], data["p2"], data["p3"]

    # Ball 1: 1 run
    engine.process_ball(match.id, BallInput(batsman_runs=1))
    db_session.refresh(innings)
    assert innings.current_striker_id == p2.id

    # Ball 2: Wicket of striker (p2), p3 comes in
    engine.process_ball(
        match.id,
        BallInput(
            is_wicket=True,
            dismissal_type="caught",
            player_out_id=p2.id,
            new_batsman_name_or_id=str(p3.id),
        ),
    )
    db_session.refresh(innings)
    assert innings.total_wickets == 1
    assert innings.current_striker_id == p3.id

    # Now UNDO the wicket ball!
    undone_ball, status = undoer.undo_last_ball(match.id)
    db_session.refresh(innings)
    assert innings.total_wickets == 0
    assert innings.legal_balls == 1
    assert innings.current_striker_id == p2.id  # p2 restored to striker!
    assert innings.current_non_striker_id == p1.id
    assert status["total_wickets"] == 0

def test_innings_switch_and_target_chase(db_session, setup_match):
    engine = ScoringEngine(db_session)
    data = setup_match
    match = data["match"]
    innings = data["innings"]
    p1, p2, p3 = data["p1"], data["p2"], data["p3"]

    # Match has 2 overs (12 balls) or 2 wickets for all-out (players_per_side = 3, max_wickets = 2)
    # Let's take 2 wickets to end 1st innings (All Out)
    engine.process_ball(
        match.id,
        BallInput(batsman_runs=4, is_wicket=True, player_out_id=p1.id, new_batsman_name_or_id=str(p3.id))
    )
    engine.process_ball(
        match.id,
        BallInput(batsman_runs=0, is_wicket=True, player_out_id=p3.id)
    )

    db_session.refresh(match)
    # 1st innings is completed with 4 runs
    assert match.status == "innings_break"
    assert match.current_innings_id is not None

    # Setup 2nd innings openers
    second_inn = db_session.get(Innings, match.current_innings_id)
    assert second_inn.innings_number == 2
    assert second_inn.target_runs == 5
    assert second_inn.batting_team_name == "Australia"

    second_inn.current_striker_id = data["b1"].id
    second_inn.current_non_striker_id = data["b2"].id
    second_inn.current_bowler_id = p1.id
    match.status = "in_progress"
    db_session.commit()

    # Australia hits a 6 off ball 1 -> target 5 chased!
    b, status = engine.process_ball(match.id, BallInput(batsman_runs=6))
    db_session.refresh(match)
    assert match.status == "completed"
    assert match.winner_team == "Australia"
    assert "wickets" in match.win_margin
