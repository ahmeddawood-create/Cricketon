import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR / 'cricket.db'}")
SECRET_KEY = os.getenv("SECRET_KEY", "gully-cricket-super-secret-key-2026")
APP_TITLE = "Cricketon"
APP_DESCRIPTION = "Mobile-first Gully & Weekend Cricket Scoring App"
