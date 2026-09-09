from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

from app.config import APP_TITLE, APP_DESCRIPTION
from app.db import init_db
from app.routers import (
    matches_router,
    scoring_router,
    scorecard_router,
    players_router,
    views_router,
)

BASE_DIR = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and tables
    init_db()
    yield

app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static folder
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
(static_dir / "css").mkdir(exist_ok=True)
(static_dir / "js").mkdir(exist_ok=True)
(static_dir / "icons").mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include API and View routers
app.include_router(matches_router)
app.include_router(scoring_router)
app.include_router(scorecard_router)
app.include_router(players_router)
app.include_router(views_router)
