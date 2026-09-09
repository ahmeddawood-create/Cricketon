from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.db import get_session
from app.models.match import Match, Innings
from app.models.player import Player, MatchPlayer
from app.models.ball_event import BallEvent
from app.schemas.ball_schema import BallInput, SelectBowlerInput, SelectBatsmanInput
from app.engine.state_machine import ScoringEngine
from app.engine.undo_manager import UndoManager
from app.services.scorecard_service import ScorecardService

router = APIRouter(prefix="/api/matches", tags=["scoring"])

@router.post("/{match_id}/ball")
def record_ball(match_id: int, payload: BallInput, session: Session = Depends(get_session)):
    engine = ScoringEngine(session)
    try:
        ball_event, status_info = engine.process_ball(match_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fetch fresh live snapshot
    match = session.get(Match, match_id)
    innings = session.get(Innings, match.current_innings_id) if match.current_innings_id else None
    scorecard_svc = ScorecardService(session)
    inn_scorecard = scorecard_svc.get_innings_scorecard(innings) if innings else None

    return {
        "status": "success",
        "ball_id": ball_event.id,
        "status_info": status_info,
        "innings": inn_scorecard,
        "match_status": match.status,
    }

@router.post("/{match_id}/undo")
def undo_ball(match_id: int, session: Session = Depends(get_session)):
    undoer = UndoManager(session)
    try:
        undone_ball, status_info = undoer.undo_last_ball(match_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    match = session.get(Match, match_id)
    innings = session.get(Innings, match.current_innings_id) if match.current_innings_id else None
    scorecard_svc = ScorecardService(session)
    inn_scorecard = scorecard_svc.get_innings_scorecard(innings) if innings else None

    return {
        "status": "success",
        "status_info": status_info,
        "innings": inn_scorecard,
        "match_status": match.status,
    }

@router.post("/{match_id}/select-bowler")
def select_bowler(match_id: int, payload: SelectBowlerInput, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match or not match.current_innings_id:
        raise HTTPException(status_code=404, detail="Active match/innings not found")

    innings = session.get(Innings, match.current_innings_id)
    bowler = session.get(Player, payload.bowler_id)
    if not bowler:
        raise HTTPException(status_code=404, detail="Player not found")

    # Check consecutive over unless force=True
    if not payload.force and innings.legal_balls > 0 and (innings.legal_balls % 6 == 0):
        last_ball = session.exec(
            select(BallEvent)
            .where(BallEvent.innings_id == innings.id, BallEvent.is_legal == True)
            .order_by(BallEvent.id.desc())
        ).first()
        if last_ball and last_ball.bowler_id == bowler.id:
            raise HTTPException(
                status_code=400,
                detail=f"{bowler.name} bowled the previous over. A bowler cannot bowl consecutive overs in standard cricket."
            )

    innings.current_bowler_id = bowler.id
    session.commit()

    return {
        "message": f"{bowler.name} selected as bowler",
        "bowler": {"id": bowler.id, "name": bowler.name},
    }

@router.post("/{match_id}/select-batsman")
def select_batsman(match_id: int, payload: SelectBatsmanInput, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match or not match.current_innings_id:
        raise HTTPException(status_code=404, detail="Active match/innings not found")

    innings = session.get(Innings, match.current_innings_id)
    batsman = None
    if payload.batsman_id:
        batsman = session.get(Player, payload.batsman_id)
    elif payload.batsman_name_or_id:
        try:
            bid = int(payload.batsman_name_or_id)
            batsman = session.get(Player, bid)
        except ValueError:
            clean_name = str(payload.batsman_name_or_id).strip()
            batsman = session.exec(select(Player).where(Player.name == clean_name)).first()
            if not batsman:
                batsman = Player(name=clean_name)
                session.add(batsman)
                session.flush()
            # Link to match
            mp = session.exec(
                select(MatchPlayer).where(MatchPlayer.match_id == match.id, MatchPlayer.player_id == batsman.id)
            ).first()
            if not mp:
                session.add(MatchPlayer(match_id=match.id, player_id=batsman.id, team_name=innings.batting_team_name))
                session.flush()

    if not batsman:
        raise HTTPException(status_code=404, detail="Player not found")

    if payload.is_striker:
        innings.current_striker_id = batsman.id
    else:
        innings.current_non_striker_id = batsman.id

    session.commit()

    return {
        "message": f"{batsman.name} selected as {'striker' if payload.is_striker else 'non-striker'}",
        "batsman": {"id": batsman.id, "name": batsman.name},
    }

@router.post("/{match_id}/swap-strike")
def swap_strike(match_id: int, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match or not match.current_innings_id:
        raise HTTPException(status_code=404, detail="Active match/innings not found")

    innings = session.get(Innings, match.current_innings_id)
    if not innings.current_striker_id or not innings.current_non_striker_id:
        raise HTTPException(status_code=400, detail="Cannot swap strike with only one batsman")

    innings.current_striker_id, innings.current_non_striker_id = (
        innings.current_non_striker_id,
        innings.current_striker_id,
    )
    session.commit()

    return {
        "message": "Strike swapped successfully",
        "striker_id": innings.current_striker_id,
        "non_striker_id": innings.current_non_striker_id,
    }

@router.post("/{match_id}/start-second-innings")
def start_second_innings(
    match_id: int,
    striker_id: int,
    non_striker_id: Optional[int] = None,
    bowler_id: int = 0,
    session: Session = Depends(get_session),
):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Find 2nd innings
    innings = session.exec(
        select(Innings).where(Innings.match_id == match.id, Innings.innings_number == 2)
    ).first()
    if not innings:
        raise HTTPException(status_code=400, detail="Second innings not ready")

    innings.current_striker_id = striker_id
    innings.current_non_striker_id = non_striker_id
    innings.current_bowler_id = bowler_id
    match.current_innings_id = innings.id
    match.status = "in_progress"
    session.commit()

    return {
        "message": "Second innings started",
        "innings_id": innings.id,
        "batting_team": innings.batting_team_name,
        "bowling_team": innings.bowling_team_name,
        "target": innings.target_runs,
    }
