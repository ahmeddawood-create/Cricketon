from typing import Optional, Tuple
from sqlmodel import Session, select
from app.models.match import Match, MatchSettings, Innings
from app.models.ball_event import BallEvent, Wicket
from app.models.player import MatchPlayer, Player
from app.schemas.ball_schema import BallInput
from app.engine.rules import get_max_wickets, is_over_complete, format_overs

class ScoringEngine:
    def __init__(self, session: Session):
        self.session = session

    def process_ball(self, match_id: int, ball_input: BallInput) -> Tuple[BallEvent, dict]:
        """
        Process a ball event for the active innings in the match.
        Returns the created BallEvent and status metadata.
        """
        match = self.session.get(Match, match_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")
        if match.status != "in_progress":
            raise ValueError(f"Match is not in progress (current status: {match.status})")

        innings = self.session.get(Innings, match.current_innings_id)
        if not innings:
            raise ValueError("No active innings found for match")

        settings = self.session.exec(
            select(MatchSettings).where(MatchSettings.match_id == match.id)
        ).first()
        if not settings:
            settings = MatchSettings(match_id=match.id)
            self.session.add(settings)
            self.session.flush()

        # Validate active players
        if not innings.current_striker_id:
            raise ValueError("No active striker selected")
        if not innings.current_bowler_id:
            raise ValueError("No active bowler selected for this over")
        if not settings.last_man_standing and not innings.current_non_striker_id:
            raise ValueError("No active non-striker selected")

        # Capture pre-state snapshot for undo
        pre_striker_id = innings.current_striker_id
        pre_non_striker_id = innings.current_non_striker_id
        pre_bowler_id = innings.current_bowler_id
        pre_total_runs = innings.total_runs
        pre_total_wickets = innings.total_wickets
        pre_legal_balls = innings.legal_balls

        # Determine legality & runs
        batsman_runs = ball_input.batsman_runs
        extra_type = ball_input.extra_type
        extra_runs = ball_input.extra_runs
        is_legal = True
        total_ball_runs = 0

        # Validate invalid dismissals on extras according to cricket laws
        if ball_input.is_wicket:
            dismissal = (ball_input.dismissal_type or "bowled").lower()
            if extra_type == "no_ball" and dismissal in ("bowled", "caught", "stumped", "hit_wicket"):
                raise ValueError(
                    f"Under cricket rules, a batsman cannot be out '{dismissal}' on a No Ball (only Run Out is allowed)."
                )
            if extra_type == "wide" and dismissal in ("bowled", "caught"):
                raise ValueError(
                    f"Under cricket rules, a batsman cannot be out '{dismissal}' on a Wide (only Stumped or Run Out is allowed)."
                )

        if extra_type == "wide":
            is_legal = not settings.wide_reball
            wide_base = settings.wide_runs
            total_extra = wide_base + extra_runs
            extra_runs = total_extra
            batsman_runs = 0  # wide runs don't count off the bat
            innings.wide_runs += total_extra
            total_ball_runs = total_extra

        elif extra_type == "no_ball":
            is_legal = not settings.no_ball_reball
            nb_base = settings.no_ball_runs
            total_extra = nb_base + extra_runs
            extra_runs = total_extra
            innings.no_ball_runs += total_extra
            total_ball_runs = batsman_runs + total_extra

        elif extra_type in ("bye", "leg_bye"):
            is_legal = True
            if extra_type == "bye":
                innings.bye_runs += extra_runs
            else:
                innings.leg_bye_runs += extra_runs
            total_ball_runs = extra_runs
            batsman_runs = 0  # byes are extras, not off the bat

        elif extra_type == "penalty":
            is_legal = False
            innings.penalty_runs += extra_runs
            total_ball_runs = extra_runs
            batsman_runs = 0

        else:
            # Standard legal delivery
            extra_type = None
            extra_runs = 0
            is_legal = True
            total_ball_runs = batsman_runs

        # Update innings totals
        innings.total_runs += total_ball_runs
        if is_legal:
            innings.legal_balls += 1

        over_number = pre_legal_balls // 6
        ball_in_over = (pre_legal_balls % 6) + 1 if is_legal else (pre_legal_balls % 6)

        # Create BallEvent record
        ball_event = BallEvent(
            innings_id=innings.id,
            over_number=over_number,
            ball_in_over=ball_in_over,
            striker_id=pre_striker_id,
            non_striker_id=pre_non_striker_id,
            bowler_id=pre_bowler_id,
            batsman_runs=batsman_runs,
            extra_type=extra_type,
            extra_runs=extra_runs,
            is_legal=is_legal,
            is_wicket=ball_input.is_wicket,
            pre_striker_id=pre_striker_id,
            pre_non_striker_id=pre_non_striker_id,
            pre_bowler_id=pre_bowler_id,
            pre_total_runs=pre_total_runs,
            pre_total_wickets=pre_total_wickets,
            pre_legal_balls=pre_legal_balls,
        )
        self.session.add(ball_event)
        self.session.flush()

        # Handle Wicket if applicable
        wicket_record = None
        player_out_id = None
        if ball_input.is_wicket:
            max_wickets = get_max_wickets(match.players_per_side, settings.last_man_standing)
            max_balls = match.overs_per_innings * 6
            new_total_wickets = innings.total_wickets + 1

            # Check if this wicket will end the innings or if lone batsman remains in LMS
            is_all_out = new_total_wickets >= max_wickets
            is_overs_complete = is_legal and innings.legal_balls >= max_balls
            is_target_chased = (
                innings.innings_number == 2
                and innings.target_runs is not None
                and innings.total_runs >= innings.target_runs
            )
            is_lms_lone_survivor = (
                settings.last_man_standing
                and new_total_wickets >= match.players_per_side - 1
            )

            will_innings_end = is_all_out or is_overs_complete or is_target_chased

            if not will_innings_end and not is_lms_lone_survivor:
                if not ball_input.new_batsman_name_or_id or not str(ball_input.new_batsman_name_or_id).strip():
                    raise ValueError("Selecting the next batter is compulsory after the fall of a wicket.")

            innings.total_wickets += 1
            dismissal = ball_input.dismissal_type or "bowled"
            player_out_id = ball_input.player_out_id or pre_striker_id

            wicket_record = Wicket(
                ball_event_id=ball_event.id,
                innings_id=innings.id,
                player_out_id=player_out_id,
                dismissal_type=dismissal,
                fielder_id=ball_input.fielder_id,
            )
            self.session.add(wicket_record)
            self.session.flush()

        # Strike Rotation Calculation:
        # Determine runs physically run between wickets:
        runs_run = 0
        if extra_type in ("bye", "leg_bye"):
            runs_run = extra_runs
        elif extra_type == "wide":
            # wide base run is non-running, any additional extra_runs is runs run
            runs_run = ball_input.extra_runs
        elif extra_type == "no_ball":
            runs_run = batsman_runs + ball_input.extra_runs
        else:
            # For 4s and 6s, batsmen don't physically run
            if batsman_runs not in (4, 6):
                runs_run = batsman_runs

        next_striker = pre_striker_id
        next_non_striker = pre_non_striker_id

        # Rotate strike on odd physical runs
        if runs_run % 2 != 0 and next_non_striker is not None:
            next_striker, next_non_striker = next_non_striker, next_striker

        # Handle batsman out update
        if ball_input.is_wicket:
            new_batsman_id = None
            if ball_input.new_batsman_name_or_id:
                try:
                    new_batsman_id = int(ball_input.new_batsman_name_or_id)
                except ValueError:
                    # Create player if string name provided
                    new_p = Player(name=str(ball_input.new_batsman_name_or_id).strip())
                    self.session.add(new_p)
                    self.session.flush()
                    new_batsman_id = new_p.id

            if player_out_id == next_striker:
                next_striker = new_batsman_id
            elif player_out_id == next_non_striker:
                next_non_striker = new_batsman_id

            # Last Man Standing: if only 1 batsman remains, promote to striker
            if settings.last_man_standing and next_striker is None and next_non_striker is not None:
                next_striker = next_non_striker
                next_non_striker = None

        # Check over completion
        over_ended = False
        if is_legal and (innings.legal_balls % 6 == 0):
            over_ended = True
            # Rotate strike on over completion if two batsmen are batting
            if next_striker and next_non_striker:
                next_striker, next_non_striker = next_non_striker, next_striker
            # Bowler must change for the next over
            innings.current_bowler_id = None

        innings.current_striker_id = next_striker
        innings.current_non_striker_id = next_non_striker

        # Check match / innings termination conditions
        max_balls = match.overs_per_innings * 6
        max_wickets = get_max_wickets(match.players_per_side, settings.last_man_standing)
        innings_over = False

        # In 2nd innings: check if target is achieved
        if innings.innings_number == 2 and innings.target_runs is not None:
            if innings.total_runs >= innings.target_runs:
                innings.is_completed = True
                match.status = "completed"
                match.winner_team = innings.batting_team_name
                wickets_left = match.players_per_side - innings.total_wickets
                match.win_margin = f"won by {wickets_left} wickets"
                innings_over = True

        # Check all out or overs complete
        if not innings_over:
            if innings.total_wickets >= max_wickets or innings.legal_balls >= max_balls:
                innings.is_completed = True
                innings_over = True

                if innings.innings_number == 1:
                    # 1st innings finished -> Setup 2nd innings
                    match.status = "innings_break"
                    target = innings.total_runs + 1
                    second_innings = Innings(
                        match_id=match.id,
                        innings_number=2,
                        batting_team_name=innings.bowling_team_name,
                        bowling_team_name=innings.batting_team_name,
                        target_runs=target,
                    )
                    self.session.add(second_innings)
                    self.session.flush()
                    match.current_innings_id = second_innings.id
                else:
                    # 2nd innings finished without reaching target
                    match.status = "completed"
                    if innings.target_runs and innings.total_runs == (innings.target_runs - 1):
                        match.winner_team = "Tie"
                        match.win_margin = "Match tied"
                    else:
                        match.winner_team = innings.bowling_team_name
                        runs_margin = (innings.target_runs - 1) - innings.total_runs if innings.target_runs else 0
                        match.win_margin = f"won by {runs_margin} runs"

        self.session.commit()

        status_info = {
            "over_ended": over_ended,
            "innings_over": innings_over,
            "match_status": match.status,
            "needs_bowler": innings.current_bowler_id is None and not innings.is_completed,
            "needs_batsman": (innings.current_striker_id is None or (not settings.last_man_standing and innings.current_non_striker_id is None)) and not innings.is_completed,
            "total_runs": innings.total_runs,
            "total_wickets": innings.total_wickets,
            "overs_str": format_overs(innings.legal_balls),
        }

        return ball_event, status_info
