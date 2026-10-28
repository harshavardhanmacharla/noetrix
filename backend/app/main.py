"""
TestPilot API — main application entry point.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import create_tables, get_db
from app.dependencies import get_current_user, get_user_org_ids
import app.models  # noqa: F401 — registers all ORM models with Base.metadata
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_run import TestRun
from app.models.user import User
from app.routers import auth, data_driven, discovery, health, organizations, project_variables, projects, reports, test_cases, test_runs

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: run startup tasks before yielding, cleanup after."""
    # Create DB tables
    logger.info("Creating database tables...")
    create_tables()

    # Ensure artifacts directory exists
    artifacts_path = Path(settings.ARTIFACTS_DIR)
    artifacts_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Artifacts directory ready: {artifacts_path.resolve()}")

    yield  # Application runs here

    logger.info("TestPilot API shutting down.")


app = FastAPI(
    title="TestPilot API",
    version="1.0.0",
    description="Test automation platform API for managing and executing browser-based tests.",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow the Vite/React frontend origin
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(discovery.router)
app.include_router(data_driven.router)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(projects.router)
app.include_router(project_variables.router)
app.include_router(test_cases.router)
app.include_router(test_runs.router)
app.include_router(reports.router)


# ---------------------------------------------------------------------------
# Dashboard statistics (aggregated view for the home page)
# ---------------------------------------------------------------------------
@app.get("/api/dashboard/stats", tags=["Dashboard"])
async def dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return aggregated platform statistics for the dashboard scoped to user's organizations."""
    user_org_ids = get_user_org_ids(current_user, db)

    if not current_user.is_superuser:
        if not user_org_ids:
            return {
                "total_organizations": 0,
                "total_projects": 0,
                "total_test_cases": 0,
                "total_runs": 0,
                "passed_runs": 0,
                "failed_runs": 0,
                "recent_runs": [],
            }
        total_orgs = (
            db.query(func.count(Organization.id))
            .filter(Organization.id.in_(user_org_ids))
            .scalar() or 0
        )
        total_projects = (
            db.query(func.count(Project.id))
            .filter(Project.org_id.in_(user_org_ids))
            .scalar() or 0
        )
        total_test_cases = (
            db.query(func.count(TestCase.id))
            .join(Project, Project.id == TestCase.project_id)
            .filter(Project.org_id.in_(user_org_ids), TestCase.is_active.is_(True))
            .scalar() or 0
        )
        total_runs = (
            db.query(func.count(TestRun.id))
            .join(Project, Project.id == TestRun.project_id)
            .filter(Project.org_id.in_(user_org_ids))
            .scalar() or 0
        )
        passed_runs = (
            db.query(func.count(TestRun.id))
            .join(Project, Project.id == TestRun.project_id)
            .filter(Project.org_id.in_(user_org_ids), TestRun.status == "passed")
            .scalar() or 0
        )
        failed_runs = (
            db.query(func.count(TestRun.id))
            .join(Project, Project.id == TestRun.project_id)
            .filter(Project.org_id.in_(user_org_ids), TestRun.status == "failed")
            .scalar() or 0
        )
        recent_runs = (
            db.query(TestRun)
            .join(Project, Project.id == TestRun.project_id)
            .filter(Project.org_id.in_(user_org_ids))
            .order_by(TestRun.created_at.desc())
            .limit(10)
            .all()
        )
    else:
        total_orgs = db.query(func.count(Organization.id)).scalar() or 0
        total_projects = db.query(func.count(Project.id)).scalar() or 0
        total_test_cases = (
            db.query(func.count(TestCase.id))
            .filter(TestCase.is_active.is_(True))
            .scalar() or 0
        )
        total_runs = db.query(func.count(TestRun.id)).scalar() or 0
        passed_runs = db.query(func.count(TestRun.id)).filter(TestRun.status == "passed").scalar() or 0
        failed_runs = db.query(func.count(TestRun.id)).filter(TestRun.status == "failed").scalar() or 0
        recent_runs = (
            db.query(TestRun)
            .order_by(TestRun.created_at.desc())
            .limit(10)
            .all()
        )

    return {
        "total_organizations": total_orgs,
        "total_projects": total_projects,
        "total_test_cases": total_test_cases,
        "total_runs": total_runs,
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "recent_runs": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "status": r.status,
                "total_tests": r.total_tests,
                "passed_tests": r.passed_tests,
                "failed_tests": r.failed_tests,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in recent_runs
        ],
    }
