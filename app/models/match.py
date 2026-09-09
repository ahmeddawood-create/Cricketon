from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field

class MatchSettings(SQLModel, table=True):
    __tablename__ = "match_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id", unique=True, index=True)
    last_man_standing: bool = Field(default=False)
    wide_runs: int = Field(default=1)
    no_ball_runs: int = Field(default=1)
    wide_reball: bool = Field(default=True)
    no_ball_reball: bool = Field(default=True)
    free_hit_on_no_ball: bool = Field(default=False)

class Match(SQLModel, table=True):
    __tablename__ = "matches"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_name: str = Field(default="Weekend Match")
    venue: Optional[str] = Field(default=None)
    overs_per_innings: int = Field(default=6)
    players_per_side: int = Field(default=8)
    max_overs_per_bowler: Optional[int] = Field(default=None)
    team_a_name: str = Field(default="Team A")
    team_b_name: str = Field(default="Team B")
    toss_winner_team: Optional[str] = Field(default=None)
    toss_decision: Optional[str] = Field(default=None)  # 'bat' or 'bowl'
    status: str = Field(default="created")  # 'created', 'in_progress', 'innings_break', 'completed'
    current_innings_id: Optional[int] = Field(default=None)
    winner_team: Optional[str] = Field(default=None)
    win_margin: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Innings(SQLModel, table=True):
    __tablename__ = "innings"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id", index=True)
    innings_number: int = Field(default=1)  # 1 or 2
    batting_team_name: str
    bowling_team_name: str
    total_runs: int = Field(default=0)
    total_wickets: int = Field(default=0)
    legal_balls: int = Field(default=0)
    wide_runs: int = Field(default=0)
    no_ball_runs: int = Field(default=0)
    bye_runs: int = Field(default=0)
    leg_bye_runs: int = Field(default=0)
    penalty_runs: int = Field(default=0)
    target_runs: Optional[int] = Field(default=None)
    is_completed: bool = Field(default=False)
    current_striker_id: Optional[int] = Field(default=None)
    current_non_striker_id: Optional[int] = Field(default=None)
    current_bowler_id: Optional[int] = Field(default=None)
