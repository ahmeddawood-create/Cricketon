from typing import Optional
from app.models.match import MatchSettings

def get_max_wickets(players_per_side: int, last_man_standing: bool) -> int:
    """Returns the number of wickets required for an all-out innings."""
    if last_man_standing:
        return players_per_side
    return max(1, players_per_side - 1)

def is_over_complete(legal_balls: int) -> bool:
    """Returns True if the current over is completed (multiples of 6 legal balls)."""
    return legal_balls > 0 and (legal_balls % 6 == 0)

def format_overs(legal_balls: int) -> str:
    """Formats legal balls into cricket overs string, e.g. 7 balls -> '1.1'."""
    overs = legal_balls // 6
    balls = legal_balls % 6
    return f"{overs}.{balls}"

def calculate_run_rate(total_runs: int, legal_balls: int) -> float:
    """Calculates current run rate per 6 balls."""
    if legal_balls == 0:
        return 0.0
    return round((total_runs / legal_balls) * 6, 2)

def calculate_required_run_rate(runs_needed: int, balls_remaining: int) -> Optional[float]:
    """Calculates required run rate for the chasing team."""
    if runs_needed <= 0:
        return 0.0
    if balls_remaining <= 0:
        return 99.99
    return round((runs_needed / balls_remaining) * 6, 2)
