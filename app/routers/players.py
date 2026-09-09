from typing import List
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.db import get_session
from app.models.player import Player, MatchPlayer
from app.models.ball_event import BallEvent, Wicket
from app.engine.rules import format_overs

router = APIRouter(prefix="/api/players", tags=["players"])

@router.get("")
def list_players(session: Session = Depends(get_session)):
    players = session.exec(select(Player).order_by(Player.name.asc())).all()
    return players

@router.get("/{player_id}/stats")
def get_player_stats(player_id: int, session: Session = Depends(get_session)):
    player = session.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    # Batting stats across all balls
    batting_balls = session.exec(
        select(BallEvent).where(BallEvent.striker_id == player.id)
    ).all()

    innings_runs = defaultdict(int)
    total_runs = 0
    total_balls_faced = 0
    fours = 0
    sixes = 0

    for b in batting_balls:
        if b.extra_type != "wide":
            total_balls_faced += 1
        if b.batsman_runs > 0 and b.extra_type not in ("bye", "leg_bye"):
            total_runs += b.batsman_runs
            innings_runs[b.innings_id] += b.batsman_runs
            if b.batsman_runs == 4:
                fours += 1
            elif b.batsman_runs == 6:
                sixes += 1

    highest_score = max(innings_runs.values()) if innings_runs else 0
    strike_rate = round((total_runs / total_balls_faced * 100), 2) if total_balls_faced > 0 else 0.0

    # Bowling stats across all balls
    bowling_balls = session.exec(
        select(BallEvent).where(BallEvent.bowler_id == player.id)
    ).all()

    legal_bowled = 0
    runs_conceded = 0
    for b in bowling_balls:
        if b.is_legal:
            legal_bowled += 1
        if b.extra_type == "wide":
            runs_conceded += b.extra_runs
        elif b.extra_type == "no_ball":
            runs_conceded += b.batsman_runs + b.extra_runs
        elif b.extra_type not in ("bye", "leg_bye", "penalty"):
            runs_conceded += b.batsman_runs

    # Wickets credited to this bowler
    credited_wickets = session.exec(
        select(Wicket)
        .join(BallEvent, BallEvent.id == Wicket.ball_event_id)
        .where(
            BallEvent.bowler_id == player.id,
            Wicket.dismissal_type.in_(["bowled", "caught", "stumped", "hit_wicket"])
        )
    ).all()

    economy = round((runs_conceded / legal_bowled * 6), 2) if legal_bowled > 0 else 0.0

    # Matches played count
    match_count = len(session.exec(select(MatchPlayer).where(MatchPlayer.player_id == player.id)).all())

    return {
        "id": player.id,
        "name": player.name,
        "nickname": player.nickname,
        "matches_played": match_count,
        "batting": {
            "innings_count": len(innings_runs),
            "runs": total_runs,
            "balls": total_balls_faced,
            "highest_score": highest_score,
            "fours": fours,
            "sixes": sixes,
            "strike_rate": strike_rate,
        },
        "bowling": {
            "overs": format_overs(legal_bowled),
            "legal_balls": legal_bowled,
            "runs_conceded": runs_conceded,
            "wickets": len(credited_wickets),
            "economy": economy,
        },
    }

@router.delete("/cleanup/unused")
def cleanup_unused_players(session: Session = Depends(get_session)):
    """Clean up players who have never bowled or batted in any match."""
    players = session.exec(select(Player)).all()
    deleted_names = []
    for p in players:
        balls = session.exec(
            select(BallEvent).where(
                (BallEvent.striker_id == p.id) |
                (BallEvent.non_striker_id == p.id) |
                (BallEvent.bowler_id == p.id)
            )
        ).first()
        if not balls:
            mps = session.exec(select(MatchPlayer).where(MatchPlayer.player_id == p.id)).all()
            for mp in mps:
                session.delete(mp)
            session.flush()
            session.delete(p)
            deleted_names.append(p.name)
    session.commit()
    return {"message": f"Cleaned up {len(deleted_names)} unused players", "deleted_players": deleted_names}

@router.delete("/{player_id}")
def delete_player(player_id: int, force: bool = False, session: Session = Depends(get_session)):
    """Delete a player. If force=False, prevents deleting players who have delivery logs in matches."""
    player = session.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    balls_count = len(session.exec(
        select(BallEvent).where(
            (BallEvent.striker_id == player.id) |
            (BallEvent.non_striker_id == player.id) |
            (BallEvent.bowler_id == player.id)
        )
    ).all())

    if balls_count > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"Player '{player.name}' has {balls_count} recorded deliveries in match history. Pass force=true to delete anyway."
        )

    # Clean up wickets involving player
    wickets = session.exec(select(Wicket).where((Wicket.player_out_id == player.id) | (Wicket.fielder_id == player.id))).all()
    for w in wickets:
        session.delete(w)

    # Clean up match player entries
    mps = session.exec(select(MatchPlayer).where(MatchPlayer.player_id == player.id)).all()
    for mp in mps:
        session.delete(mp)

    # If forced and balls exist, delete those ball events
    if balls_count > 0 and force:
        balls = session.exec(
            select(BallEvent).where(
                (BallEvent.striker_id == player.id) |
                (BallEvent.non_striker_id == player.id) |
                (BallEvent.bowler_id == player.id)
            )
        ).all()
        for b in balls:
            session.delete(b)

    session.flush()
    player_name = player.name
    session.delete(player)
    session.commit()
    return {"message": f"Player '{player_name}' deleted successfully", "id": player_id}

