from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from pathlib import Path
from app.db import get_session
from app.models.match import Match, MatchSettings, Innings
from app.models.player import Player, MatchPlayer

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(include_in_schema=False)

@router.get("/")
def index_view(request: Request, session: Session = Depends(get_session)):
    matches = session.exec(select(Match).order_by(Match.created_at.desc())).all()
    players = session.exec(select(Player).order_by(Player.name.asc())).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "matches": matches,
            "players": players,
        },
    )

@router.get("/match/{match_id}/toss")
def toss_view(match_id: int, request: Request, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    players_a = session.exec(
        select(Player).join(MatchPlayer, MatchPlayer.player_id == Player.id)
        .where(MatchPlayer.match_id == match.id, MatchPlayer.team_name == match.team_a_name)
    ).all()

    players_b = session.exec(
        select(Player).join(MatchPlayer, MatchPlayer.player_id == Player.id)
        .where(MatchPlayer.match_id == match.id, MatchPlayer.team_name == match.team_b_name)
    ).all()

    settings = session.exec(select(MatchSettings).where(MatchSettings.match_id == match.id)).first()

    return templates.TemplateResponse(
        request=request,
        name="toss.html",
        context={
            "match": match,
            "settings": settings,
            "team_a_players": [{"id": p.id, "name": p.name} for p in players_a],
            "team_b_players": [{"id": p.id, "name": p.name} for p in players_b],
        },
    )

@router.get("/match/{match_id}/score")
def scorer_view(match_id: int, request: Request, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    settings = session.exec(select(MatchSettings).where(MatchSettings.match_id == match.id)).first()

    return templates.TemplateResponse(
        request=request,
        name="scorer.html",
        context={
            "match": match,
            "settings": settings,
        },
    )

@router.get("/match/{match_id}/live")
def live_view(match_id: int, request: Request, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    return templates.TemplateResponse(
        request=request,
        name="live.html",
        context={
            "match": match,
        },
    )

@router.get("/match/{match_id}/scorecard")
def scorecard_view(match_id: int, request: Request, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    return templates.TemplateResponse(
        request=request,
        name="scorecard.html",
        context={
            "match": match,
        },
    )

@router.get("/players")
def players_view(request: Request, session: Session = Depends(get_session)):
    players = session.exec(select(Player).order_by(Player.name.asc())).all()
    return templates.TemplateResponse(
        request=request,
        name="players.html",
        context={
            "players": players,
        },
    )
