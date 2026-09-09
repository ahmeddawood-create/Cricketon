from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from app.db import get_session
from app.models.match import Match, Innings
from app.services.scorecard_service import ScorecardService
from app.schemas.scorecard_schema import MatchScorecard, InningsScorecard

router = APIRouter(prefix="/api/matches", tags=["scorecard"])

@router.get("/{match_id}/scorecard", response_model=MatchScorecard)
def get_match_scorecard(match_id: int, session: Session = Depends(get_session)):
    service = ScorecardService(session)
    try:
        scorecard = service.get_match_scorecard(match_id)
        return scorecard
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/{match_id}/live-summary")
def get_live_summary(match_id: int, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if not match.current_innings_id:
        return {
            "status": match.status,
            "match_name": match.match_name,
            "team_a": match.team_a_name,
            "team_b": match.team_b_name,
            "result": f"{match.winner_team} {match.win_margin}" if match.winner_team else None,
        }

    innings = session.get(Innings, match.current_innings_id)
    service = ScorecardService(session)
    inn_scorecard = service.get_innings_scorecard(innings) if innings else None

    return {
        "match_id": match.id,
        "match_name": match.match_name,
        "status": match.status,
        "result": f"{match.winner_team} {match.win_margin}" if match.winner_team else None,
        "innings": inn_scorecard,
    }
