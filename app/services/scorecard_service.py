from typing import List, Dict, Optional
from collections import defaultdict
from sqlmodel import Session, select
from app.models.match import Match, Innings
from app.models.ball_event import BallEvent, Wicket
from app.models.player import Player, MatchPlayer
from app.schemas.scorecard_schema import (
    BatsmanScore,
    BowlerScore,
    WicketFall,
    ExtrasDetail,
    InningsScorecard,
    MatchScorecard,
)
from app.engine.rules import format_overs, calculate_run_rate, calculate_required_run_rate

class ScorecardService:
    def __init__(self, session: Session):
        self.session = session

    def get_player_name_map(self) -> Dict[int, str]:
        players = self.session.exec(select(Player)).all()
        return {p.id: p.name for p in players if p.id is not None}

    def get_innings_scorecard(self, innings: Innings) -> InningsScorecard:
        match = self.session.get(Match, innings.match_id)
        player_names = self.get_player_name_map()

        # Fetch balls and wickets
        balls = self.session.exec(
            select(BallEvent)
            .where(BallEvent.innings_id == innings.id)
            .order_by(BallEvent.id.asc())
        ).all()

        wickets = self.session.exec(
            select(Wicket)
            .where(Wicket.innings_id == innings.id)
            .order_by(Wicket.id.asc())
        ).all()

        wicket_by_ball_id = {w.ball_event_id: w for w in wickets}
        wicket_by_player_id = {w.player_out_id: w for w in wickets}

        # Batsmen stats accumulator
        batting_order: List[int] = []
        if innings.current_striker_id and innings.current_striker_id not in batting_order:
            batting_order.append(innings.current_striker_id)
        if innings.current_non_striker_id and innings.current_non_striker_id not in batting_order:
            batting_order.append(innings.current_non_striker_id)

        batsmen_runs = defaultdict(int)
        batsmen_balls = defaultdict(int)
        batsmen_fours = defaultdict(int)
        batsmen_sixes = defaultdict(int)

        # Bowlers stats accumulator
        bowling_order: List[int] = []
        if innings.current_bowler_id and innings.current_bowler_id not in bowling_order:
            bowling_order.append(innings.current_bowler_id)

        bowler_balls = defaultdict(int)
        bowler_runs = defaultdict(int)
        bowler_wickets = defaultdict(int)
        bowler_wides = defaultdict(int)
        bowler_no_balls = defaultdict(int)
        over_runs = defaultdict(lambda: defaultdict(int))  # over_number -> bowler_id -> runs

        # Fall of wickets tracking
        fall_of_wickets: List[WicketFall] = []
        running_score = 0
        running_legal_balls = 0
        wicket_count = 0

        # Recent balls in current active over
        recent_balls: List[str] = []
        active_over_number = balls[-1].over_number if balls else 0

        for b in balls:
            if b.striker_id not in batting_order:
                batting_order.append(b.striker_id)
            if b.non_striker_id and b.non_striker_id not in batting_order:
                batting_order.append(b.non_striker_id)
            if b.bowler_id not in bowling_order:
                bowling_order.append(b.bowler_id)

            # Batsman stats
            batsman_runs = b.batsman_runs
            extra_type = b.extra_type
            extra_runs = b.extra_runs

            # Ball faced counts if it is legal or a no_ball (wides/penalties do not count as ball faced)
            if extra_type not in ("wide", "penalty"):
                batsmen_balls[b.striker_id] += 1

            if batsman_runs > 0 and extra_type not in ("bye", "leg_bye"):
                batsmen_runs[b.striker_id] += batsman_runs
                if batsman_runs == 4:
                    batsmen_fours[b.striker_id] += 1
                elif batsman_runs == 6:
                    batsmen_sixes[b.striker_id] += 1

            # Bowler stats
            if b.is_legal:
                bowler_balls[b.bowler_id] += 1
                running_legal_balls += 1

            # Bowler runs conceded (batsman runs + wides + no_balls; byes/leg byes not conceded by bowler)
            conceded = 0
            if extra_type == "wide":
                conceded = extra_runs
                bowler_wides[b.bowler_id] += 1
            elif extra_type == "no_ball":
                conceded = batsman_runs + extra_runs
                bowler_no_balls[b.bowler_id] += 1
            elif extra_type in ("bye", "leg_bye", "penalty"):
                conceded = 0
            else:
                conceded = batsman_runs

            bowler_runs[b.bowler_id] += conceded
            over_runs[b.over_number][b.bowler_id] += conceded

            # Running score
            ball_total = (extra_runs if extra_type in ("wide", "penalty")
                          else (batsman_runs + extra_runs if extra_type == "no_ball"
                          else (extra_runs if extra_type in ("bye", "leg_bye")
                          else batsman_runs)))
            running_score += ball_total

            # Wickets
            if b.is_wicket:
                wicket_count += 1
                w = wicket_by_ball_id.get(b.id)
                if w:
                    if w.dismissal_type in ("bowled", "caught", "stumped", "hit_wicket"):
                        bowler_wickets[b.bowler_id] += 1
                    fall_of_wickets.append(
                        WicketFall(
                            wicket_number=wicket_count,
                            score=running_score,
                            overs_str=format_overs(running_legal_balls),
                            player_name=player_names.get(w.player_out_id, f"Player #{w.player_out_id}"),
                        )
                    )

            # Build badge label for recent over
            if b.over_number == active_over_number:
                badge = ""
                if b.is_wicket:
                    badge = "W"
                    if batsman_runs > 0:
                        badge = f"W+{batsman_runs}"
                elif extra_type == "wide":
                    badge = "Wd" if extra_runs == 1 else f"Wd+{extra_runs}"
                elif extra_type == "no_ball":
                    badge = "Nb" if batsman_runs == 0 and extra_runs == 1 else f"Nb+{batsman_runs}"
                elif extra_type == "bye":
                    badge = f"B{extra_runs}"
                elif extra_type == "leg_bye":
                    badge = f"Lb{extra_runs}"
                elif batsman_runs == 0:
                    badge = "•"
                else:
                    badge = str(batsman_runs)
                recent_balls.append(badge)

        # Maiden overs calculation
        bowler_maidens = defaultdict(int)
        for over_idx, b_map in over_runs.items():
            for b_id, runs in b_map.items():
                # Check if 6 legal balls bowled in this over
                legal_in_over = sum(1 for b in balls if b.over_number == over_idx and b.bowler_id == b_id and b.is_legal)
                if legal_in_over == 6 and runs == 0:
                    bowler_maidens[b_id] += 1

        # Build Batsmen Scores list
        batsmen_list: List[BatsmanScore] = []
        for pid in batting_order:
            runs = batsmen_runs[pid]
            faced = batsmen_balls[pid]
            sr = round((runs / faced * 100), 2) if faced > 0 else 0.0
            is_out = pid in wicket_by_player_id
            dismissal_str = "not out"

            if is_out:
                w = wicket_by_player_id[pid]
                f_name = player_names.get(w.fielder_id, "") if w.fielder_id else ""
                # Find bowler for this ball
                b_ev = next((b for b in balls if b.id == w.ball_event_id), None)
                b_name = player_names.get(b_ev.bowler_id, "") if b_ev else ""

                if w.dismissal_type == "bowled":
                    dismissal_str = f"b {b_name}"
                elif w.dismissal_type == "caught":
                    dismissal_str = f"c {f_name} b {b_name}" if f_name else f"c & b {b_name}"
                elif w.dismissal_type == "run_out":
                    dismissal_str = f"run out ({f_name})" if f_name else "run out"
                elif w.dismissal_type == "stumped":
                    dismissal_str = f"st {f_name} b {b_name}" if f_name else f"st b {b_name}"
                elif w.dismissal_type == "hit_wicket":
                    dismissal_str = f"hit wicket b {b_name}"
                else:
                    dismissal_str = w.dismissal_type

            is_batting = pid in (innings.current_striker_id, innings.current_non_striker_id)
            is_striker = pid == innings.current_striker_id

            batsmen_list.append(
                BatsmanScore(
                    player_id=pid,
                    player_name=player_names.get(pid, f"Player #{pid}"),
                    runs=runs,
                    balls=faced,
                    fours=batsmen_fours[pid],
                    sixes=batsmen_sixes[pid],
                    strike_rate=sr,
                    is_out=is_out,
                    dismissal_text=dismissal_str,
                    is_batting=is_batting,
                    is_striker=is_striker,
                )
            )

        # Build Bowlers Scores list
        bowlers_list: List[BowlerScore] = []
        for pid in bowling_order:
            b_balls = bowler_balls[pid]
            b_runs = bowler_runs[pid]
            econ = round((b_runs / b_balls * 6), 2) if b_balls > 0 else 0.0
            bowlers_list.append(
                BowlerScore(
                    player_id=pid,
                    player_name=player_names.get(pid, f"Player #{pid}"),
                    overs_str=format_overs(b_balls),
                    legal_balls=b_balls,
                    maidens=bowler_maidens[pid],
                    runs_conceded=b_runs,
                    wickets=bowler_wickets[pid],
                    economy=econ,
                    wides=bowler_wides[pid],
                    no_balls=bowler_no_balls[pid],
                    is_bowling=(pid == innings.current_bowler_id),
                )
            )

        # Extras detail
        extras = ExtrasDetail(
            total=(innings.wide_runs + innings.no_ball_runs + innings.bye_runs + innings.leg_bye_runs + innings.penalty_runs),
            wides=innings.wide_runs,
            no_balls=innings.no_ball_runs,
            byes=innings.bye_runs,
            leg_byes=innings.leg_bye_runs,
            penalties=innings.penalty_runs,
        )

        # Required run rate and calculations
        runs_needed = None
        balls_remaining = None
        rrr = None
        if innings.target_runs is not None:
            if innings.is_completed:
                runs_needed = 0
                balls_remaining = 0
                rrr = 0.0
            else:
                runs_needed = max(0, innings.target_runs - innings.total_runs)
                total_innings_balls = (match.overs_per_innings * 6) if match else 36
                balls_remaining = max(0, total_innings_balls - innings.legal_balls)
                rrr = calculate_required_run_rate(runs_needed, balls_remaining)

        last_over_bowler_id = None
        if innings.legal_balls > 0 and (innings.legal_balls % 6 == 0):
            last_legal = [b for b in balls if b.is_legal]
            if last_legal:
                last_over_bowler_id = last_legal[-1].bowler_id

        return InningsScorecard(
            innings_id=innings.id,
            innings_number=innings.innings_number,
            batting_team=innings.batting_team_name,
            bowling_team=innings.bowling_team_name,
            total_runs=innings.total_runs,
            total_wickets=innings.total_wickets,
            overs_str=format_overs(innings.legal_balls),
            run_rate=calculate_run_rate(innings.total_runs, innings.legal_balls),
            target_runs=innings.target_runs,
            required_run_rate=rrr,
            runs_needed=runs_needed,
            balls_remaining=balls_remaining,
            extras=extras,
            batsmen=batsmen_list,
            bowlers=bowlers_list,
            fall_of_wickets=fall_of_wickets,
            recent_balls=recent_balls,
            is_completed=innings.is_completed,
            last_over_bowler_id=last_over_bowler_id,
        )

    def get_match_scorecard(self, match_id: int) -> MatchScorecard:
        match = self.session.get(Match, match_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")

        innings_records = self.session.exec(
            select(Innings)
            .where(Innings.match_id == match.id)
            .order_by(Innings.innings_number.asc())
        ).all()

        innings_scorecards = [self.get_innings_scorecard(inn) for inn in innings_records]

        result_str = None
        if match.status == "completed":
            if match.winner_team == "Tie":
                result_str = "Match Tied"
            elif match.winner_team:
                result_str = f"{match.winner_team} {match.win_margin}"

        current_inn_num = 1
        if match.current_innings_id:
            curr = self.session.get(Innings, match.current_innings_id)
            if curr:
                current_inn_num = curr.innings_number

        return MatchScorecard(
            match_id=match.id,
            match_name=match.match_name,
            venue=match.venue,
            overs_per_innings=match.overs_per_innings,
            status=match.status,
            result=result_str,
            innings=innings_scorecards,
            current_innings_number=current_inn_num,
        )
