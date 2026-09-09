from typing import Optional
from pydantic import BaseModel, Field

class BallInput(BaseModel):
    batsman_runs: int = Field(default=0, ge=0, le=7)
    extra_type: Optional[str] = None  # 'wide', 'no_ball', 'bye', 'leg_bye', 'penalty'
    extra_runs: int = Field(default=0, ge=0, le=10)
    is_wicket: bool = False
    dismissal_type: Optional[str] = None  # 'bowled', 'caught', 'run_out', 'stumped', 'hit_wicket'
    player_out_id: Optional[int] = None  # striker or non-striker
    fielder_id: Optional[int] = None
    new_batsman_name_or_id: Optional[str] = None  # incoming batsman if wicket fell

class SelectBowlerInput(BaseModel):
    bowler_id: int
    force: bool = False

class SelectBatsmanInput(BaseModel):
    batsman_id: Optional[int] = None
    batsman_name_or_id: Optional[str] = None
    is_striker: bool = True
