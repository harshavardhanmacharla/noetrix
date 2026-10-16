# ✈️ TestPilot — Test Automation Platform

A modern, full-stack web application for QA engineers to upload test cases, execute them with Playwright browser automation, and view detailed execution results including screenshots, logs, and recorded videos.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Backend | Python 3.11 + FastAPI |
| Automation | Playwright for Python |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy + Alembic |
| Containers | Docker + Docker Compose |

---

## Prerequisites (Windows)

- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
- **Node.js 20+** — [nodejs.org](https://nodejs.org/)
- **Git** — [git-scm.com](https://git-scm.com/)
- Optional: **Docker Desktop** for containerized deployment

Verify installations:
```powershell
python --version   # 3.11+
node --version     # 20+
npm --version
```

---

## Quick Start (Local Development)

### 1. Clone / Navigate to Project

```powershell
cd "C:\Users\<YourName>\testpilot-platform"
```

### 2. Backend Setup

```powershell
cd backend

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# If execution policy blocks scripts:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Copy environment config
copy .env.example .env
# Edit .env if needed (defaults work for local dev)

# Start the backend
uvicorn app.main:app --reload --port 8000
```

Backend will be available at: **http://localhost:8000**
Interactive API docs: **http://localhost:8000/docs**

### 3. Frontend Setup

Open a **new PowerShell window**:

```powershell
cd "C:\Users\<YourName>\testpilot-platform\frontend"

# Install dependencies
npm install

# Copy environment config
copy .env.example .env

# Start the dev server
npm run dev
```

Frontend will be available at: **http://localhost:5173**

---

## Using the Application

### Step 1: Create an Organization
Navigate to **Organizations** → Click **New Organization** → Enter name and save.

### Step 2: Create a Project
Navigate to **Projects** → Click **New Project** → Enter name and the **App URL** of the web application you want to test (e.g., `http://localhost:3001`).

### Step 3: Configure the Target App URL
Navigate to **Settings** → Select your project → Enter/update the App URL.

### Step 4: Upload Test Cases
Navigate to **Test Cases** → Select your project → Download the **CSV template** → Fill in your test steps → Upload the CSV.

#### CSV Format
```csv
test_case_id,test_name,step_number,action,target,value,expected_result
TC001,Load Homepage,1,navigate,https://example.com,,
TC001,Load Homepage,2,verify_url,,,https://example.com
TC001,Load Homepage,3,verify_text,h1,,Welcome
TC002,Login,1,navigate,https://example.com/login,,
TC002,Login,2,fill,#email,user@example.com,
TC002,Login,3,fill,#password,secret123,
TC002,Login,4,click,button[type='submit'],,
TC002,Login,5,verify_url,,,https://example.com/dashboard
```

#### Supported Actions
| Action | Description | `target` | `value` |
|--------|-------------|----------|---------|
| `navigate` | Go to URL | URL to navigate to | — |
| `fill` | Type into field | CSS selector | Text to type |
| `click` | Click element | CSS selector | — |
| `verify_url` | Assert current URL | — | Expected URL substring |
| `verify_text` | Assert text exists | CSS selector | Expected text |
| `discover_page` | Save visible headings and interactive controls from the current page to `discovery.json` | — | — |

### Step 5: Run Tests
Navigate to **Test Execution** → Select your project → Check test cases → Click **Run Selected Tests**.

### Step 6: View Results
Navigate to **Reports** → Select a run to view:
- Pass/fail per test case
- Execution logs
- Screenshots (on failure)
- Recorded video of the browser session

---

## Sample Data

Sample CSV files are in the `sample_data/` directory:
- `template.csv` — empty template with correct column headers
- `sample_test_cases.csv` — example test cases (update URLs to match your app)

---

## Running Tests

### Backend Tests
```powershell
cd backend
.\venv\Scripts\Activate.ps1
pytest tests/ -v
```

### Frontend Build Check
```powershell
cd frontend
npm run build
```

---

## Project Structure

```
testpilot-platform/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application entry
│   │   ├── config.py            # Environment configuration
│   │   ├── database.py          # SQLAlchemy setup
│   │   ├── models/              # Database models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── routers/             # API route handlers
│   │   └── services/            # Business logic (CSV validator, Playwright)
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # Pytest test suite
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/               # Page components (6 pages)
│   │   ├── components/          # Reusable UI components
│   │   ├── api/                 # API client functions
│   │   └── types/               # TypeScript interfaces
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── sample_data/
│   ├── template.csv
│   └── sample_test_cases.csv
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Docker Deployment

```powershell
# Copy and configure environment
copy .env.example .env
# Edit .env with secure values

# Build and start all services
docker compose up --build

# Services:
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

---

## Database Migrations (Alembic)

```powershell
cd backend
.\venv\Scripts\Activate.ps1

# Create a new migration after model changes
alembic revision --autogenerate -m "description of change"

# Apply migrations
alembic upgrade head

# Rollback one version
alembic downgrade -1
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./testpilot.db` | Database connection string |
| `SECRET_KEY` | — | JWT signing key (required in production) |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins |
| `ARTIFACTS_DIR` | `./artifacts` | Directory for screenshots/videos |
| `PLAYWRIGHT_HEADLESS` | `true` | Run browser headlessly |
| `PLAYWRIGHT_TIMEOUT_MS` | `30000` | Browser action timeout (ms) |
| `VITE_API_URL` | `http://localhost:8000` | Backend URL (frontend env var) |

---

## Known Limitations (MVP)

- Authentication is not yet implemented — all data is visible without login (multi-tenant models are in place)
- Video playback requires the browser to support the WebM codec
- Large CSV files (>10MB) are rejected; split into multiple uploads
- Test execution is synchronous per test case — parallel execution is a future enhancement

---

## Security Notes

- **Never commit your `.env` file** — it's in `.gitignore`
- Change `SECRET_KEY` to a long random string in production
- Use PostgreSQL with a strong password in production
- The CSV validator blocks code execution — only predefined actions are supported

---

## Troubleshooting

**PowerShell execution policy error:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Playwright browser not found:**
```powershell
cd backend
.\venv\Scripts\Activate.ps1
playwright install chromium
```

**Port already in use:**
```powershell
# Find process using port 8000
netstat -ano | findstr :8000
# Kill it
taskkill /PID <PID> /F
```

**CORS errors in browser:**
Ensure `CORS_ORIGINS` in `backend/.env` includes your frontend URL.

---

## License

MIT — See LICENSE file for details.
