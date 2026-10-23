"""Pytest fixtures and configuration."""
import os
import pytest

# Ensure tests run against local in-memory SQLite database
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-secret-key-12345678901234567890")
os.environ.setdefault("SECRET_ENCRYPTION_KEY", "u1Z5vWqN49gKpX1pU7jP2lQ8rT3vY6wZ9bC4eF8hJ1k=")
os.environ.setdefault("ARTIFACTS_DIR", "./test_artifacts")
