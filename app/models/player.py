from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field

class Player(SQLModel, table=True):
    __tablename__ = "players"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    nickname: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MatchPlayer(SQLModel, table=True):
    __tablename__ = "match_players"

    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="matches.id", index=True)
    player_id: int = Field(foreign_key="players.id", index=True)
    team_name: str
    batting_order: Optional[int] = None
