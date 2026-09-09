from app.routers.matches import router as matches_router
from app.routers.scoring import router as scoring_router
from app.routers.scorecard import router as scorecard_router
from app.routers.players import router as players_router
from app.routers.views import router as views_router

__all__ = [
    "matches_router",
    "scoring_router",
    "scorecard_router",
    "players_router",
    "views_router",
]
