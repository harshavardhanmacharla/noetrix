"""Pytest fixtures and configuration."""
import os
import pytest

# Ensure tests run against local in-memory SQLite database
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-secret-key-12345678901234567890")
os.environ.setdefault("ARTIFACTS_DIR", "./test_artifacts")
