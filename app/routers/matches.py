from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from app.db import get_session
from app.models.match import Match, MatchSettings, Innings
from app.models.player import Player, MatchPlayer
from app.models.ball_event import BallEvent, Wicket
from app.schemas.match_schema import MatchCreate, TossRequest, MatchStatusResponse, MatchSettingsSchema

router = APIRouter(prefix="/api/matches", tags=["matches"])

@router.post("", response_model=MatchStatusResponse)
def create_match(payload: MatchCreate, session: Session = Depends(get_session)):
    # 1. Create Match
    match = Match(
        match_name=payload.match_name,
        venue=payload.venue,
        overs_per_innings=payload.overs_per_innings,
        players_per_side=payload.players_per_side,
        max_overs_per_bowler=payload.max_overs_per_bowler,
        team_a_name=payload.team_a_name.strip(),
        team_b_name=payload.team_b_name.strip(),
        status="created",
    )
    session.add(match)
    session.commit()
    session.refresh(match)

    # 2. Create Gully MatchSettings
    st = payload.settings
    settings = MatchSettings(
        match_id=match.id,
        last_man_standing=st.last_man_standing if st else False,
        wide_runs=st.wide_runs if st else 1,
        no_ball_runs=st.no_ball_runs if st else 1,
        wide_reball=st.wide_reball if st else True,
        no_ball_reball=st.no_ball_reball if st else True,
        free_hit_on_no_ball=st.free_hit_on_no_ball if st else False,
    )
    session.add(settings)

    # 3. Create or find Players and link to Match
    def add_team_players(player_names: List[str], team_name: str):
        for idx, name in enumerate(player_names):
            clean_name = name.strip()
            if not clean_name:
                continue
            player = session.exec(select(Player).where(Player.name == clean_name)).first()
            if not player:
                player = Player(name=clean_name)
                session.add(player)
                session.flush()
            match_player = MatchPlayer(
                match_id=match.id,
                player_id=player.id,
                team_name=team_name,
                batting_order=idx + 1,
            )
            session.add(match_player)

    add_team_players(payload.team_a_players, match.team_a_name)
    add_team_players(payload.team_b_players, match.team_b_name)
    session.commit()

    return match

@router.get("", response_model=List[MatchStatusResponse])
def list_matches(session: Session = Depends(get_session)):
    matches = session.exec(select(Match).order_by(Match.created_at.desc())).all()
    return matches

@router.get("/{match_id}")
def get_match(match_id: int, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    settings = session.exec(select(MatchSettings).where(MatchSettings.match_id == match.id)).first()
    return {"match": match, "settings": settings}

@router.get("/{match_id}/players")
def get_match_players(match_id: int, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    players_a = session.exec(
        select(Player)
        .join(MatchPlayer, MatchPlayer.player_id == Player.id)
        .where(MatchPlayer.match_id == match.id, MatchPlayer.team_name == match.team_a_name)
    ).all()

    players_b = session.exec(
        select(Player)
        .join(MatchPlayer, MatchPlayer.player_id == Player.id)
        .where(MatchPlayer.match_id == match.id, MatchPlayer.team_name == match.team_b_name)
    ).all()

    return {
        "team_a": {"name": match.team_a_name, "players": [{"id": p.id, "name": p.name} for p in players_a]},
        "team_b": {"name": match.team_b_name, "players": [{"id": p.id, "name": p.name} for p in players_b]},
    }

def _resolve_or_create_player(session: Session, match_id: int, team_name: str, name_or_id: str) -> Player:
    try:
        pid = int(name_or_id)
        p = session.get(Player, pid)
        if p:
            return p
    except ValueError:
        pass

    clean_name = name_or_id.strip()
    p = session.exec(select(Player).where(Player.name == clean_name)).first()
    if not p:
        p = Player(name=clean_name)
        session.add(p)
        session.flush()

    # Link to match if not linked
    mp = session.exec(
        select(MatchPlayer).where(MatchPlayer.match_id == match_id, MatchPlayer.player_id == p.id)
    ).first()
    if not mp:
        session.add(MatchPlayer(match_id=match_id, player_id=p.id, team_name=team_name))
        session.flush()

    return p

@router.post("/{match_id}/toss")
def record_toss(match_id: int, payload: TossRequest, session: Session = Depends(get_session)):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    match.toss_winner_team = payload.toss_winner_team.strip()
    match.toss_decision = payload.toss_decision.strip().lower()

    # Determine 1st innings batting & bowling teams
    if match.toss_decision == "bat":
        batting_team = match.toss_winner_team
        bowling_team = match.team_b_name if batting_team == match.team_a_name else match.team_a_name
    else:
        bowling_team = match.toss_winner_team
        batting_team = match.team_b_name if bowling_team == match.team_a_name else match.team_a_name

    # Resolve players
    striker = _resolve_or_create_player(session, match.id, batting_team, payload.striker_name_or_id)
    non_striker = None
    if payload.non_striker_name_or_id:
        non_striker = _resolve_or_create_player(session, match.id, batting_team, payload.non_striker_name_or_id)
    bowler = _resolve_or_create_player(session, match.id, bowling_team, payload.bowler_name_or_id)

    # Create 1st Innings
    innings = Innings(
        match_id=match.id,
        innings_number=1,
        batting_team_name=batting_team,
        bowling_team_name=bowling_team,
        current_striker_id=striker.id,
        current_non_striker_id=non_striker.id if non_striker else None,
        current_bowler_id=bowler.id,
    )
    session.add(innings)
    session.flush()

    # If custom settings provided at toss time, update them
    if payload.settings:
        st = session.exec(select(MatchSettings).where(MatchSettings.match_id == match.id)).first()
        if not st:
            st = MatchSettings(match_id=match.id)
        st.wide_runs = payload.settings.wide_runs
        st.no_ball_runs = payload.settings.no_ball_runs
        st.wide_reball = payload.settings.wide_reball
        st.no_ball_reball = payload.settings.no_ball_reball
        st.last_man_standing = payload.settings.last_man_standing
        st.free_hit_on_no_ball = payload.settings.free_hit_on_no_ball
        session.add(st)

    match.current_innings_id = innings.id
    match.status = "in_progress"
    session.commit()

    return {
        "message": "Toss and opening players recorded successfully",
        "match_id": match.id,
        "current_innings_id": innings.id,
        "batting_team": batting_team,
        "bowling_team": bowling_team,
        "striker": {"id": striker.id, "name": striker.name},
        "non_striker": {"id": non_striker.id, "name": non_striker.name} if non_striker else None,
        "bowler": {"id": bowler.id, "name": bowler.name},
    }

@router.put("/{match_id}/settings")
def update_settings(match_id: int, payload: MatchSettingsSchema, session: Session = Depends(get_session)):
    st = session.exec(select(MatchSettings).where(MatchSettings.match_id == match_id)).first()
    if not st:
        st = MatchSettings(match_id=match_id)
    st.wide_runs = payload.wide_runs
    st.no_ball_runs = payload.no_ball_runs
    st.wide_reball = payload.wide_reball
    st.no_ball_reball = payload.no_ball_reball
    st.last_man_standing = payload.last_man_standing
    st.free_hit_on_no_ball = payload.free_hit_on_no_ball
    session.add(st)
    session.commit()
    return st

def _cleanup_match_dependencies(match: Match, session: Session):
    """Deletes all innings, ball events, wickets, settings, and player associations for a match."""
    match.current_innings_id = None
    session.add(match)
    session.flush()

    innings_list = session.exec(select(Innings).where(Innings.match_id == match.id)).all()
    for inn in innings_list:
        wickets = session.exec(select(Wicket).where(Wicket.innings_id == inn.id)).all()
        for w in wickets:
            session.delete(w)
        balls = session.exec(select(BallEvent).where(BallEvent.innings_id == inn.id)).all()
        for b in balls:
            session.delete(b)
        session.flush()
        session.delete(inn)
    session.flush()

    settings = session.exec(select(MatchSettings).where(MatchSettings.match_id == match.id)).all()
    for s in settings:
        session.delete(s)

    mps = session.exec(select(MatchPlayer).where(MatchPlayer.match_id == match.id)).all()
    for mp in mps:
        session.delete(mp)
    session.flush()

@router.delete("/{match_id}")
def delete_match(match_id: int, session: Session = Depends(get_session)):
    """Permanently delete a match and all associated innings, balls, and wickets."""
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    match_name = match.match_name
    _cleanup_match_dependencies(match, session)
    session.delete(match)
    session.commit()
    return {"message": f"Match '{match_name}' deleted successfully", "id": match_id}

@router.delete("")
def delete_matches_bulk(status: Optional[str] = None, session: Session = Depends(get_session)):
    """Bulk delete matches by status ('completed', 'created', or 'all')."""
    stmt = select(Match)
    if status and status.lower() != "all":
        stmt = stmt.where(Match.status == status.lower())
    matches = session.exec(stmt).all()

    count = len(matches)
    for m in matches:
        _cleanup_match_dependencies(m, session)
        session.delete(m)
        session.flush()
    session.commit()
    return {"message": f"Deleted {count} matches", "count": count}

@router.post("/{match_id}/reset")
def reset_match(match_id: int, session: Session = Depends(get_session)):
    """Reset a match back to initial toss state, removing recorded innings and balls while preserving rosters & rules."""
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    match.current_innings_id = None
    session.add(match)
    session.flush()

    # Delete all innings, ball events, wickets
    innings_list = session.exec(select(Innings).where(Innings.match_id == match.id)).all()
    for inn in innings_list:
        wickets = session.exec(select(Wicket).where(Wicket.innings_id == inn.id)).all()
        for w in wickets:
            session.delete(w)
        balls = session.exec(select(BallEvent).where(BallEvent.innings_id == inn.id)).all()
        for b in balls:
            session.delete(b)
        session.flush()
        session.delete(inn)
    session.flush()

    match.status = "created"
    match.toss_winner_team = None
    match.toss_decision = None
    match.winner_team = None
    match.win_margin = None
    session.add(match)
    session.commit()
    return {"message": f"Match '{match.match_name}' reset to initial state", "match_id": match.id}

