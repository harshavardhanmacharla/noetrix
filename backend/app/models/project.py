"""
Project model.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    """Represents a testing project within an organization."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    app_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, comment="Target web application URL for testing"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(  # noqa: F821
        "Organization", back_populates="projects"
    )
    test_cases: Mapped[list["TestCase"]] = relationship(  # noqa: F821
        "TestCase", back_populates="project", cascade="all, delete-orphan"
    )
    test_runs: Mapped[list["TestRun"]] = relationship(  # noqa: F821
        "TestRun", back_populates="project", cascade="all, delete-orphan"
    )
    variables: Mapped[list["ProjectVariable"]] = relationship(  # noqa: F821
        "ProjectVariable", back_populates="project", cascade="all, delete-orphan"
    )
