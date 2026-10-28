"""
Live Browser Discovery ORM models.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DiscoverySession(Base):
    """Represents an interactive Live Browser Discovery session."""

    __tablename__ = "discovery_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tp_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    app_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    current_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    current_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project")  # noqa: F821
    user: Mapped["User"] = relationship("User")  # noqa: F821
    snapshots: Mapped[list["DiscoverySnapshot"]] = relationship(
        "DiscoverySnapshot",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="DiscoverySnapshot.created_at.desc()",
    )


class DiscoverySnapshot(Base):
    """Represents a captured element inventory snapshot for a specific page state."""

    __tablename__ = "discovery_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("discovery_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    page_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    elements_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inventory_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped["DiscoverySession"] = relationship(
        "DiscoverySession", back_populates="snapshots"
    )
