"""
Live Browser Discovery REST API router.
Provides endpoints to start, inspect, refresh, test targets on, and close live discovery sessions.
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, verify_project_access
from app.models.discovery import DiscoverySession, DiscoverySnapshot
from app.models.user import User
from app.schemas.discovery import (
    DiscoverySessionResponse,
    DiscoverySnapshotResponse,
    NavigateDiscoveryRequest,
    SearchInventoryRequest,
    SearchInventoryResponse,
    StartDiscoveryRequest,
    ValidateTargetRequest,
    ValidateTargetResponse,
)
from app.services.discovery_service import (
    DiscoverySessionManager,
    validate_discovery_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discovery", tags=["Live Discovery"])


def _to_session_response(session: DiscoverySession, active_worker=None) -> DiscoverySessionResponse:
    snapshots_count = len(session.snapshots) if session.snapshots else 0
    latest_snap = session.snapshots[0] if session.snapshots else None
    latest_snap_resp = None
    if latest_snap:
        inventory_dict = None
        try:
            inventory_dict = json.loads(latest_snap.inventory_data)
        except Exception:
            pass
        latest_snap_resp = DiscoverySnapshotResponse(
            id=latest_snap.id,
            session_id=latest_snap.session_id,
            page_url=latest_snap.page_url,
            page_title=latest_snap.page_title,
            elements_count=latest_snap.elements_count,
            created_at=latest_snap.created_at,
            inventory_data=inventory_dict,
        )

    current_url = session.current_url
    current_title = session.current_title
    current_status = session.status

    if active_worker and active_worker.is_active:
        current_url = active_worker.current_url or current_url
        current_title = active_worker.current_title or current_title
        current_status = "active"
    elif session.status == "active" and (not active_worker or not active_worker.is_active):
        current_status = "completed"

    return DiscoverySessionResponse(
        id=session.id,
        project_id=session.project_id,
        user_id=session.user_id,
        app_url=session.app_url,
        current_url=current_url,
        current_title=current_title,
        status=current_status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        closed_at=session.closed_at,
        snapshots_count=snapshots_count,
        latest_snapshot=latest_snap_resp,
    )


@router.post("/sessions", response_model=DiscoverySessionResponse, status_code=status.HTTP_201_CREATED)
async def start_discovery_session(
    req: StartDiscoveryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoverySessionResponse:
    """Start an interactive Playwright Chromium browser session for Live Discovery."""
    verify_project_access(req.project_id, current_user, db)

    try:
        clean_url = validate_discovery_url(req.url)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    new_session = DiscoverySession(
        project_id=req.project_id,
        user_id=current_user.id,
        app_url=clean_url,
        current_url=clean_url,
        status="active",
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    manager = DiscoverySessionManager.get_instance()
    try:
        worker = manager.start_session(
            session_id=new_session.id,
            user_id=current_user.id,
            project_id=req.project_id,
            app_url=clean_url,
            headless=req.headless,
        )
        new_session.current_url = worker.current_url
        new_session.current_title = worker.current_title
        db.commit()
        db.refresh(new_session)
        return _to_session_response(new_session, worker)
    except Exception as exc:
        new_session.status = "failed"
        new_session.closed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not launch live discovery browser: {exc}",
        )


@router.get("/sessions", response_model=List[DiscoverySessionResponse])
async def list_discovery_sessions(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[DiscoverySessionResponse]:
    """List discovery sessions for current user or project."""
    query = db.query(DiscoverySession)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(DiscoverySession.project_id == project_id)

    if not current_user.is_superuser:
        query = query.filter(DiscoverySession.user_id == current_user.id)

    sessions = query.order_by(DiscoverySession.created_at.desc()).all()
    manager = DiscoverySessionManager.get_instance()

    responses = []
    for s in sessions:
        worker = manager._workers.get(s.id)
        responses.append(_to_session_response(s, worker))
    return responses


@router.get("/sessions/{session_id}", response_model=DiscoverySessionResponse)
async def get_discovery_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoverySessionResponse:
    """Get active status and metadata of a discovery session."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    manager = DiscoverySessionManager.get_instance()
    worker = manager._workers.get(session_id)
    return _to_session_response(session, worker)


@router.post("/sessions/{session_id}/inventory", response_model=DiscoverySnapshotResponse)
async def capture_page_inventory(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoverySnapshotResponse:
    """Capture or refresh the live element inventory for the browser's current page."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    manager = DiscoverySessionManager.get_instance()
    try:
        inventory_data = manager.capture_inventory(session_id, current_user.id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Discovery session browser has ended or is inactive.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to capture element inventory: {exc}",
        )

    page_url = inventory_data.get("url") or session.current_url or session.app_url
    page_title = inventory_data.get("page_title") or ""
    elements = inventory_data.get("elements", [])

    # Update session current page info
    session.current_url = page_url
    session.current_title = page_title
    session.updated_at = datetime.now(timezone.utc)

    # Persist snapshot
    snapshot = DiscoverySnapshot(
        session_id=session.id,
        page_url=page_url,
        page_title=page_title,
        elements_count=len(elements),
        inventory_data=json.dumps(inventory_data, ensure_ascii=False),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return DiscoverySnapshotResponse(
        id=snapshot.id,
        session_id=snapshot.session_id,
        page_url=snapshot.page_url,
        page_title=snapshot.page_title,
        elements_count=snapshot.elements_count,
        created_at=snapshot.created_at,
        inventory_data=inventory_data,
    )


@router.get("/sessions/{session_id}/snapshots", response_model=List[DiscoverySnapshotResponse])
async def list_session_snapshots(
    session_id: str,
    order: Optional[str] = "asc",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[DiscoverySnapshotResponse]:
    """List all captured snapshots for a discovery session (ordered chronologically by default)."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    query = db.query(DiscoverySnapshot).filter(DiscoverySnapshot.session_id == session_id)
    if order == "desc":
        query = query.order_by(DiscoverySnapshot.created_at.desc())
    else:
        query = query.order_by(DiscoverySnapshot.created_at.asc())

    snapshots = query.all()

    results = []
    for s in snapshots:
        inv = None
        try:
            inv = json.loads(s.inventory_data)
        except Exception:
            pass
        results.append(
            DiscoverySnapshotResponse(
                id=s.id,
                session_id=s.session_id,
                page_url=s.page_url,
                page_title=s.page_title,
                elements_count=s.elements_count,
                created_at=s.created_at,
                inventory_data=inv,
            )
        )
    return results


@router.get("/sessions/{session_id}/snapshots/{snapshot_id}", response_model=DiscoverySnapshotResponse)
async def get_session_snapshot(
    session_id: str,
    snapshot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoverySnapshotResponse:
    """Get single snapshot by ID for a discovery session."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    snapshot = (
        db.query(DiscoverySnapshot)
        .filter(DiscoverySnapshot.session_id == session_id, DiscoverySnapshot.id == snapshot_id)
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found.")

    inv = None
    try:
        inv = json.loads(snapshot.inventory_data)
    except Exception:
        pass

    return DiscoverySnapshotResponse(
        id=snapshot.id,
        session_id=snapshot.session_id,
        page_url=snapshot.page_url,
        page_title=snapshot.page_title,
        elements_count=snapshot.elements_count,
        created_at=snapshot.created_at,
        inventory_data=inv,
    )


@router.get("/sessions/{session_id}/export")
async def export_discovery_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export complete discovery session with all snapshots, frames, and elements as JSON file."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    snapshots = (
        db.query(DiscoverySnapshot)
        .filter(DiscoverySnapshot.session_id == session_id)
        .order_by(DiscoverySnapshot.created_at.asc())
        .all()
    )

    snapshots_export = []
    total_elements = 0
    for s in snapshots:
        inv = None
        try:
            inv = json.loads(s.inventory_data)
        except Exception:
            inv = {}

        elements = inv.get("elements", []) if isinstance(inv, dict) else []
        headings = inv.get("headings", []) if isinstance(inv, dict) else []
        frames = inv.get("frames", []) if isinstance(inv, dict) else []
        total_elements += len(elements)

        snapshots_export.append({
            "id": s.id,
            "session_id": s.session_id,
            "page_url": s.page_url,
            "page_title": s.page_title,
            "elements_count": s.elements_count,
            "created_at": s.created_at.isoformat() if hasattr(s.created_at, "isoformat") else str(s.created_at),
            "headings": headings,
            "frames": frames,
            "elements": elements,
        })

    export_payload = {
        "schema_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "session": {
            "id": session.id,
            "project_id": session.project_id,
            "user_id": session.user_id,
            "app_url": session.app_url,
            "current_url": session.current_url,
            "current_title": session.current_title,
            "status": session.status,
            "created_at": session.created_at.isoformat() if hasattr(session.created_at, "isoformat") else str(session.created_at),
            "updated_at": session.updated_at.isoformat() if hasattr(session.updated_at, "isoformat") else str(session.updated_at),
            "closed_at": session.closed_at.isoformat() if (session.closed_at and hasattr(session.closed_at, "isoformat")) else (str(session.closed_at) if session.closed_at else None),
            "snapshots_count": len(snapshots),
        },
        "total_snapshots": len(snapshots),
        "total_elements": total_elements,
        "snapshots": snapshots_export,
    }

    content_str = json.dumps(export_payload, indent=2, ensure_ascii=False)
    filename = f"discovery_inventory_{session_id}.json"
    return Response(
        content=content_str,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/sessions/{session_id}/search-inventory", response_model=SearchInventoryResponse)
async def search_session_inventory(
    session_id: str,
    req: SearchInventoryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchInventoryResponse:
    """Search saved snapshots for candidate elements matching a natural-language query or intent."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    query_db = db.query(DiscoverySnapshot).filter(DiscoverySnapshot.session_id == session_id)
    if req.snapshot_id:
        query_db = query_db.filter(DiscoverySnapshot.id == req.snapshot_id)

    snapshots = query_db.order_by(DiscoverySnapshot.created_at.asc()).all()
    from app.services.discovery_service import search_saved_snapshots
    matches_raw = search_saved_snapshots(snapshots, req.query, req.action)

    # If live browser session is active, test candidate locators against live DOM
    manager = DiscoverySessionManager.get_instance()
    worker = manager._workers.get(session_id)
    if worker and worker.is_active:
        for m in matches_raw[:5]:
            rec_loc = m.get("recommended_locator")
            if rec_loc:
                try:
                    val_res = worker.execute_command(
                        "VALIDATE_TARGET",
                        (rec_loc, req.action or "click"),
                        timeout=3.0,
                    )
                    if isinstance(val_res, dict) and val_res.get("status") == "resolved_unique":
                        m["live_validated"] = True
                        m["live_match_count"] = val_res.get("matched_count", 1)
                except Exception:
                    pass

    return SearchInventoryResponse(
        session_id=session_id,
        query=req.query,
        action=req.action,
        matches=matches_raw,
        total_matches=len(matches_raw),
    )


@router.post("/sessions/{session_id}/validate-target", response_model=ValidateTargetResponse)
async def validate_target(
    session_id: str,
    req: ValidateTargetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ValidateTargetResponse:
    """Test how a natural-language target or selector resolves against the live browser DOM."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    manager = DiscoverySessionManager.get_instance()
    try:
        res = manager.validate_target(session_id, current_user.id, req.target, req.action)
        return ValidateTargetResponse(**res)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Discovery session browser has ended or is inactive.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Target validation failed: {exc}",
        )


@router.post("/sessions/{session_id}/navigate", response_model=DiscoverySessionResponse)
async def navigate_session(
    session_id: str,
    req: NavigateDiscoveryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DiscoverySessionResponse:
    """Navigate the active discovery browser to a new URL."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    manager = DiscoverySessionManager.get_instance()
    try:
        nav_result = manager.navigate(session_id, current_user.id, req.url)
        session.current_url = nav_result.get("url")
        session.current_title = nav_result.get("title")
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        worker = manager._workers.get(session_id)
        return _to_session_response(session, worker)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Discovery session browser has ended or is inactive.",
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Navigation failed: {exc}",
        )


@router.post("/sessions/{session_id}/close", status_code=status.HTTP_200_OK)
async def close_discovery_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """End a live discovery session and close the browser, preserving all saved snapshots."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery session not found.")

    if not current_user.is_superuser and session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this session.")

    manager = DiscoverySessionManager.get_instance()
    manager.close_session(session_id, current_user.id)

    session.status = "completed"
    session.closed_at = datetime.now(timezone.utc)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()

    snapshots_count = db.query(DiscoverySnapshot).filter(DiscoverySnapshot.session_id == session_id).count()

    return {
        "status": "completed",
        "session_id": session_id,
        "snapshots_saved": snapshots_count,
        "message": f"Discovery session ended. {snapshots_count} snapshots remain saved and accessible.",
    }


