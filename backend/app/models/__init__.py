# Import all models to register them with Base.metadata
# This ensures create_all() and Alembic see every table.
from app.models.organization import Organization, OrganizationMembership  # noqa: F401
from app.models.user import User, PasswordResetToken  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.project_variable import ProjectVariable  # noqa: F401
from app.models.test_case import TestCase, TestStep  # noqa: F401
from app.models.test_run import TestRun, TestResult, Artifact  # noqa: F401
