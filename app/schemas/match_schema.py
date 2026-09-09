from typing import Optional, List
from pydantic import BaseModel, Field

class MatchSettingsSchema(BaseModel):
    last_man_standing: bool = False
    wide_runs: int = 1
    no_ball_runs: int = 1
    wide_reball: bool = True
    no_ball_reball: bool = True
    free_hit_on_no_ball: bool = False

class MatchCreate(BaseModel):
    match_name: str = "Weekend Gully Match"
    venue: Optional[str] = "Local Ground"
    overs_per_innings: int = Field(default=6, ge=1, le=50)
    players_per_side: int = Field(default=8, ge=2, le=20)
    max_overs_per_bowler: Optional[int] = None
    team_a_name: str = "Team A"
    team_b_name: str = "Team B"
    team_a_players: List[str] = Field(default_factory=list)
    team_b_players: List[str] = Field(default_factory=list)
    settings: Optional[MatchSettingsSchema] = None

class TossRequest(BaseModel):
    toss_winner_team: str  # must match team_a_name or team_b_name
    toss_decision: str  # 'bat' or 'bowl'
    striker_name_or_id: str
    non_striker_name_or_id: Optional[str] = None
    bowler_name_or_id: str
    settings: Optional[MatchSettingsSchema] = None

class MatchStatusResponse(BaseModel):
    id: int
    match_name: str
    venue: Optional[str]
    overs_per_innings: int
    players_per_side: int
    team_a_name: str
    team_b_name: str
    toss_winner_team: Optional[str]
    toss_decision: Optional[str]
    status: str
    winner_team: Optional[str]
    win_margin: Optional[str]
    current_innings_id: Optional[int]
