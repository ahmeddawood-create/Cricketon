from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field

class BallEvent(SQLModel, table=True):
    __tablename__ = "ball_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    innings_id: int = Field(foreign_key="innings.id", index=True)
    over_number: int = Field(default=0)  # 0, 1, 2...
    ball_in_over: int = Field(default=1)  # 1 to 6 (for legal delivery sequence)
    striker_id: int = Field(foreign_key="players.id")
    non_striker_id: Optional[int] = Field(default=None, foreign_key="players.id")
    bowler_id: int = Field(foreign_key="players.id")
    batsman_runs: int = Field(default=0)
    extra_type: Optional[str] = Field(default=None)  # 'wide', 'no_ball', 'bye', 'leg_bye', 'penalty'
    extra_runs: int = Field(default=0)
    is_legal: bool = Field(default=True)
    is_wicket: bool = Field(default=False)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Snapshot of state right BEFORE this ball was bowled, allowing 100% accurate atomic UNDO:
    pre_striker_id: Optional[int] = None
    pre_non_striker_id: Optional[int] = None
    pre_bowler_id: Optional[int] = None
    pre_total_runs: int = Field(default=0)
    pre_total_wickets: int = Field(default=0)
    pre_legal_balls: int = Field(default=0)

class Wicket(SQLModel, table=True):
    __tablename__ = "wickets"

    id: Optional[int] = Field(default=None, primary_key=True)
    ball_event_id: int = Field(foreign_key="ball_events.id", index=True)
    innings_id: int = Field(foreign_key="innings.id", index=True)
    player_out_id: int = Field(foreign_key="players.id")
    dismissal_type: str  # 'bowled', 'caught', 'run_out', 'stumped', 'hit_wicket', 'retired_hurt', 'timed_out'
    fielder_id: Optional[int] = Field(default=None, foreign_key="players.id")
