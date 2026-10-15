"""
Artifact service: manages file storage paths for screenshots, videos, and logs.
"""
import os
import uuid
from pathlib import Path
from typing import Optional


class ArtifactService:
    """Handles filesystem operations for test run artifacts."""

    def __init__(self, artifacts_dir: str):
        self.base_dir = Path(artifacts_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        """Return (and create) the directory for a specific test run."""
        path = self.base_dir / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def result_dir(self, run_id: str, result_id: str) -> Path:
        """Return (and create) the directory for a specific test result."""
        path = self.run_dir(run_id) / "results" / result_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def screenshot_path(self, run_id: str, result_id: str, suffix: str = "failure") -> Path:
        """Build the path for a screenshot artifact."""
        return self.result_dir(run_id, result_id) / f"screenshot_{suffix}.png"

    def video_path(self, run_id: str) -> Path:
        """Build the path for a video artifact."""
        return self.run_dir(run_id) / "recording.webm"

    def video_dir(self, run_id: str) -> Path:
        """Return the video directory for Playwright video recording."""
        vdir = self.run_dir(run_id) / "videos"
        vdir.mkdir(parents=True, exist_ok=True)
        return vdir

    def log_path(self, run_id: str, result_id: str) -> Path:
        """Build the path for a text log artifact."""
        return self.result_dir(run_id, result_id) / "run.log"

    def file_size(self, path: Path) -> Optional[int]:
        """Return file size in bytes, or None if the file doesn't exist."""
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return None

    def relative_path(self, absolute_path: Path) -> str:
        """Return a path relative to the artifacts base directory for storage in DB."""
        try:
            return str(absolute_path.relative_to(self.base_dir))
        except ValueError:
            return str(absolute_path)

    def absolute_path(self, relative_path: str) -> Path:
        """Resolve a relative path stored in DB back to an absolute path."""
        p = Path(relative_path)
        if p.is_absolute():
            return p
        return self.base_dir / relative_path
