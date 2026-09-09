from typing import Optional, List, Dict
from pydantic import BaseModel

class BatsmanScore(BaseModel):
    player_id: int
    player_name: str
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    strike_rate: float = 0.0
    is_out: bool = False
    dismissal_text: str = "not out"
    is_batting: bool = False
    is_striker: bool = False

class BowlerScore(BaseModel):
    player_id: int
    player_name: str
    overs_str: str = "0.0"
    legal_balls: int = 0
    maidens: int = 0
    runs_conceded: int = 0
    wickets: int = 0
    economy: float = 0.0
    wides: int = 0
    no_balls: int = 0
    is_bowling: bool = False

class WicketFall(BaseModel):
    wicket_number: int
    score: int
    overs_str: str
    player_name: str

class ExtrasDetail(BaseModel):
    total: int = 0
    wides: int = 0
    no_balls: int = 0
    byes: int = 0
    leg_byes: int = 0
    penalties: int = 0

class InningsScorecard(BaseModel):
    innings_id: int
    innings_number: int
    batting_team: str
    bowling_team: str
    total_runs: int = 0
    total_wickets: int = 0
    overs_str: str = "0.0"
    run_rate: float = 0.0
    target_runs: Optional[int] = None
    required_run_rate: Optional[float] = None
    runs_needed: Optional[int] = None
    balls_remaining: Optional[int] = None
    extras: ExtrasDetail = ExtrasDetail()
    batsmen: List[BatsmanScore] = []
    bowlers: List[BowlerScore] = []
    fall_of_wickets: List[WicketFall] = []
    recent_balls: List[str] = []
    is_completed: bool = False
    last_over_bowler_id: Optional[int] = None

class MatchScorecard(BaseModel):
    match_id: int
    match_name: str
    venue: Optional[str] = None
    overs_per_innings: int
    status: str
    result: Optional[str] = None
    innings: List[InningsScorecard] = []
    current_innings_number: int = 1
