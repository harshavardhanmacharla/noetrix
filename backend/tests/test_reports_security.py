"""
Security regression tests for artifact file serving and path traversal protection.
"""
import os
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database import create_tables
from app.dependencies import get_current_user
from app.main import app
from app.models.user import User

settings = get_settings()


@pytest.fixture(autouse=True)
def init_db():
    """Ensure database tables exist in the test environment."""
    create_tables()
    yield


@pytest.fixture(autouse=True)
def override_auth():
    """Default authenticated superuser fixture for path traversal regression tests."""
    admin_user = User(
        id="admin-test-id",
        email="admin@example.com",
        full_name="Admin User",
        is_active=True,
        is_superuser=True,
    )
    app.dependency_overrides[get_current_user] = lambda: admin_user
    yield admin_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def temp_artifacts_env(tmp_path):
    """
    Setup an isolated temporary artifacts directory with test artifacts
    and sensitive outside files for traversal testing.
    """
    original_artifacts_dir = settings.ARTIFACTS_DIR

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_dir = artifacts_dir / "runs" / "test_run_1"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Valid artifacts inside the allowed directory
    valid_png = run_dir / "screenshot.png"
    valid_png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest")

    valid_webm = run_dir / "video.webm"
    valid_webm.write_bytes(b"\x1a\x45\xdf\xa3webm_test_data")

    valid_log = run_dir / "run.log"
    valid_log.write_text("Execution log line 1\nExecution log line 2\n", encoding="utf-8")

    valid_json = run_dir / "discovery.json"
    valid_json.write_text('{"elements": [], "headings": []}', encoding="utf-8")

    # Disallowed file type inside artifacts directory
    script_file = run_dir / "malicious.py"
    script_file.write_text("import os; print('exploit')", encoding="utf-8")

    # Sensitive files OUTSIDE the artifacts directory
    outside_secret = tmp_path / "outside_secret.txt"
    outside_secret.write_text("TOP_SECRET_CREDENTIAL_DATA", encoding="utf-8")

    outside_env = tmp_path / ".env"
    outside_env.write_text("DATABASE_URL=secret_db_url\nSECRET_KEY=confidential\n", encoding="utf-8")

    # Point settings to temporary artifacts directory
    settings.ARTIFACTS_DIR = str(artifacts_dir)

    yield {
        "tmp_path": tmp_path,
        "artifacts_dir": artifacts_dir,
        "run_dir": run_dir,
        "valid_png": valid_png,
        "valid_webm": valid_webm,
        "valid_log": valid_log,
        "valid_json": valid_json,
        "script_file": script_file,
        "outside_secret": outside_secret,
        "outside_env": outside_env,
    }

    # Teardown: restore original configuration
    settings.ARTIFACTS_DIR = original_artifacts_dir


@pytest.mark.asyncio
async def test_serve_valid_artifact_relative_path(temp_artifacts_env):
    """A valid artifact inside the artifacts directory should be served with correct media type."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": "runs/test_run_1/screenshot.png"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest"


@pytest.mark.asyncio
async def test_serve_valid_artifact_with_artifacts_prefix(temp_artifacts_env):
    """Artifact paths starting with 'artifacts/' should be handled cleanly."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": "artifacts/runs/test_run_1/video.webm"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/webm"
    assert response.content == b"\x1a\x45\xdf\xa3webm_test_data"


@pytest.mark.asyncio
async def test_serve_valid_artifact_absolute_path_within_allowed_dir(temp_artifacts_env):
    """An absolute path that points strictly inside the artifacts directory should be allowed."""
    valid_path = str(temp_artifacts_env["valid_log"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": valid_path})
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "Execution log line 1" in response.text


@pytest.mark.asyncio
async def test_path_traversal_parent_directory_rejected(temp_artifacts_env):
    """Traversal attempts using '../' to reach parent files must be rejected with 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": "../outside_secret.txt"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied: Invalid artifact path."
    assert "TOP_SECRET" not in response.text


@pytest.mark.asyncio
async def test_path_traversal_deep_escape_rejected(temp_artifacts_env):
    """Deep traversal attempts (e.g. '../../.env') must be rejected with 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": "../../.env"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied: Invalid artifact path."
    assert "DATABASE_URL" not in response.text


@pytest.mark.asyncio
async def test_absolute_path_outside_allowed_dir_rejected(temp_artifacts_env):
    """Absolute paths to files outside the artifacts directory must be rejected with 403."""
    outside_file = str(temp_artifacts_env["outside_secret"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": outside_file})
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied: Invalid artifact path."
    assert "TOP_SECRET" not in response.text


@pytest.mark.asyncio
async def test_arbitrary_system_path_rejected(temp_artifacts_env):
    """Known arbitrary system paths (e.g., C:/Windows/win.ini, /etc/passwd) must be rejected with 403."""
    paths_to_test = ["C:/Windows/win.ini", "C:\\Windows\\win.ini", "/etc/passwd"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for p in paths_to_test:
            response = await client.get("/api/artifacts/file", params={"path": p})
            assert response.status_code == 403
            assert response.json()["detail"] == "Access denied: Invalid artifact path."


@pytest.mark.asyncio
async def test_disallowed_file_extension_rejected(temp_artifacts_env):
    """Files with non-whitelisted extensions (.py, .exe, .sh, etc.) must be rejected with 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": "runs/test_run_1/malicious.py"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported artifact file type."


@pytest.mark.asyncio
async def test_nonexistent_file_returns_404(temp_artifacts_env):
    """A nonexistent file inside the allowed directory must return 404 without leaking server path."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": "runs/test_run_1/missing.png"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact file not found."


@pytest.mark.asyncio
async def test_empty_and_null_byte_paths_rejected(temp_artifacts_env):
    """Empty paths and paths containing null bytes must be rejected with 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Empty path
        res_empty = await client.get("/api/artifacts/file", params={"path": ""})
        assert res_empty.status_code == 400

        # Null byte injection
        res_null = await client.get("/api/artifacts/file", params={"path": "runs/test_run_1/\x00screenshot.png"})
        assert res_null.status_code == 400


@pytest.mark.asyncio
async def test_symlink_escape_rejected_if_supported(temp_artifacts_env):
    """If symlinks are supported by the operating system, symlinks pointing outside must be rejected with 403."""
    symlink_path = temp_artifacts_env["run_dir"] / "escaped_link.png"
    try:
        os.symlink(temp_artifacts_env["outside_secret"], symlink_path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted or supported without elevated privileges on this OS.")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/artifacts/file", params={"path": "runs/test_run_1/escaped_link.png"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied: Invalid artifact path."


@pytest.mark.asyncio
async def test_unauthenticated_artifact_request_rejected(temp_artifacts_env):
    """Unauthenticated requests to artifact endpoints must receive 401 Unauthorized."""
    # Temporarily remove dependency override
    app.dependency_overrides.pop(get_current_user, None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res1 = await client.get("/api/artifacts/file", params={"path": "runs/test_run_1/screenshot.png"})
            assert res1.status_code == 401
            assert res1.json()["detail"] == "Authentication credentials were not provided."

            res2 = await client.get("/artifacts/runs/test_run_1/screenshot.png")
            assert res2.status_code == 401
            assert res2.json()["detail"] == "Authentication credentials were not provided."
    finally:
        pass


@pytest.mark.asyncio
async def test_authenticated_mounted_artifact_route(temp_artifacts_env):
    """Authenticated requests to /artifacts/{path} should serve artifact securely."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/artifacts/runs/test_run_1/screenshot.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest"

