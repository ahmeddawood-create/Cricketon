from typing import Optional, Tuple
from sqlmodel import Session, select
from app.models.match import Match, Innings
from app.models.ball_event import BallEvent, Wicket
from app.engine.rules import format_overs

class UndoManager:
    def __init__(self, session: Session):
        self.session = session

    def undo_last_ball(self, match_id: int) -> Tuple[Optional[BallEvent], dict]:
        """
        Reverts the most recently recorded delivery atomically.
        Restores previous striker, non-striker, bowler, score, wickets, and legal balls.
        """
        match = self.session.get(Match, match_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")

        current_innings = self.session.get(Innings, match.current_innings_id)
        if not current_innings:
            raise ValueError("No active innings found for match")

        # Find the last ball in the current innings
        last_ball = self.session.exec(
            select(BallEvent)
            .where(BallEvent.innings_id == current_innings.id)
            .order_by(BallEvent.id.desc())
        ).first()

        # If current innings has no balls and is 2nd innings, check if we need to revert to 1st innings
        if not last_ball and current_innings.innings_number == 2:
            first_innings = self.session.exec(
                select(Innings)
                .where(Innings.match_id == match.id, Innings.innings_number == 1)
            ).first()
            if first_innings:
                # Delete empty 2nd innings
                self.session.delete(current_innings)
                self.session.flush()
                match.current_innings_id = first_innings.id
                match.status = "in_progress"
                first_innings.is_completed = False
                self.session.commit()
                # Now find last ball in first innings
                current_innings = first_innings
                last_ball = self.session.exec(
                    select(BallEvent)
                    .where(BallEvent.innings_id == current_innings.id)
                    .order_by(BallEvent.id.desc())
                ).first()

        if not last_ball:
            raise ValueError("No balls to undo in this match")

        # Remove any wickets linked to this ball
        wickets = self.session.exec(
            select(Wicket).where(Wicket.ball_event_id == last_ball.id)
        ).all()
        for w in wickets:
            self.session.delete(w)
        self.session.flush()

        # Revert extras breakdown
        if last_ball.extra_type == "wide":
            current_innings.wide_runs = max(0, current_innings.wide_runs - last_ball.extra_runs)
        elif last_ball.extra_type == "no_ball":
            current_innings.no_ball_runs = max(0, current_innings.no_ball_runs - last_ball.extra_runs)
        elif last_ball.extra_type == "bye":
            current_innings.bye_runs = max(0, current_innings.bye_runs - last_ball.extra_runs)
        elif last_ball.extra_type == "leg_bye":
            current_innings.leg_bye_runs = max(0, current_innings.leg_bye_runs - last_ball.extra_runs)
        elif last_ball.extra_type == "penalty":
            current_innings.penalty_runs = max(0, current_innings.penalty_runs - last_ball.extra_runs)

        # Restore pre-delivery snapshot
        current_innings.current_striker_id = last_ball.pre_striker_id
        current_innings.current_non_striker_id = last_ball.pre_non_striker_id
        current_innings.current_bowler_id = last_ball.pre_bowler_id
        current_innings.total_runs = last_ball.pre_total_runs
        current_innings.total_wickets = last_ball.pre_total_wickets
        current_innings.legal_balls = last_ball.pre_legal_balls
        current_innings.is_completed = False

        # Reset match status if completed
        match.status = "in_progress"
        match.winner_team = None
        match.win_margin = None

        # Delete the ball event
        self.session.delete(last_ball)
        self.session.commit()

        status_info = {
            "message": "Last delivery undone successfully",
            "total_runs": current_innings.total_runs,
            "total_wickets": current_innings.total_wickets,
            "overs_str": format_overs(current_innings.legal_balls),
            "striker_id": current_innings.current_striker_id,
            "non_striker_id": current_innings.current_non_striker_id,
            "bowler_id": current_innings.current_bowler_id,
        }

        return last_ball, status_info
