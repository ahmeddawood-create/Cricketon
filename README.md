# 🏏 MyCricScorer

> **Mobile-First Gully & Weekend Cricket Scoring Web App**  
> Fast 1-thumb scoring, instant atomic undo, gully rule toggles, live spectator scoreboard, and WhatsApp-ready scorecard export. Built with Python (FastAPI), SQLModel, SQLite, Tailwind CSS, Alpine.js, and PWA capabilities.

---

## ✨ Features

- **Thumb-Reach Scorer UI**:
  - Outdoor high-contrast scoreboard header with CRR, Target, and Required Run Rate.
  - Active Batsmen (`*` striker, non-striker) with live runs, balls faced, boundaries, and strike rates.
  - Current Bowler spell figures (`Overs - Maidens - Runs - Wickets` and Economy).
  - Over Ribbon with colorful ball badges: `[ 0 ] [ 1 ] [ 4 ] [ 6 ] [ Wd+1 ] [ W ] [ • ]`.
  - Big touch keypad: `0`, `1`, `2`, `3`, `4`, `6`.
  - Dedicated extras drawer: `Wide`, `No Ball`, `Bye`, `Leg Bye`.
- **Gully / Street Cricket Rules**:
  - Variable overs per match (4, 6, 8, 10, 15, 20 overs).
  - Last Man Standing rule toggle.
  - Custom extra runs (e.g. 1 or 2 runs on wide/no-ball).
  - Re-ball on wide / no-ball toggle.
  - Free hit toggle.
- **Event-Driven Scoring Engine with Instant Undo**:
  - Every ball recorded as an immutable event with pre-delivery state snapshot.
  - 1-tap **UNDO** button safely reverts runs, extras, wickets, striker/non-striker positions, and bowler stats.
- **WhatsApp Shareable Scorecard**:
  - Styled high-resolution summary card with match winner badge, top batsmen, and best bowlers.
  - 1-tap PNG image download / share via `html2canvas`.
- **Spectator Live Score (`/match/{id}/live`)**:
  - Read-only real-time scoreboard auto-refreshing every 3s for teammates waiting outside the boundary.
- **Progressive Web App (PWA)**:
  - Add to Home Screen on Android & iOS.
  - Offline asset caching via service worker (`sw.js`).
- **Player Career Records**:
  - Lifetime runs, matches, highest score, boundaries, strike rate, wickets, and economy.

---

## 🚀 Getting Started

The project is completely self-contained within the Python virtual environment (`.venv`).

### 1. Activate the Virtual Environment

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
.\.venv\Scripts\activate.bat
```

### 2. Run the Application

```powershell
python run.py
```
*Or directly via uvicorn:*
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser and navigate to:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 🧪 Running Automated Tests

Run the full pytest suite inside `.venv`:

```powershell
.\.venv\Scripts\python -m pytest -v
```

Test coverage includes:
- Strike rotation on odd/even runs & boundaries
- Over completion & change of ends
- Extras (wides, no-balls, byes, leg-byes) & reball behavior
- Wickets & incoming batsman assignment
- Instant atomic undo rollback of scores, wickets, and player states
- Target chasing, innings break, and match completion
- REST API lifecycle endpoints
- Web template rendering
