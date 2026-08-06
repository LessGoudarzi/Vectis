"""Token-gated endpoint that lets the frontend's restart button relaunch
the backend process without needing shell/SSH access to the host.
"""

import logging
import os
import secrets
import sys

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from config import settings

logger = logging.getLogger("uvicorn")

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


def _reexec_process() -> None:
    """Replaces the running interpreter in place (same PID). This drops
    the current listening socket and the new process rebinds a fresh one
    on startup, so it's a self-restart that needs no external supervisor
    (docker `restart:` policy, uvicorn --reload, etc.) to bring it back.

    Scheduled as a BackgroundTask, so it only runs after this request's
    response has already been flushed to the client — execv'ing sooner
    would tear down the socket mid-response.
    """
    logger.warning("Restarting backend process now (self re-exec).")
    os.execv(sys.executable, [sys.executable, *sys.argv])


@router.post("/restart-backend")
def restart_backend(background_tasks: BackgroundTasks, x_admin_token: str = Header(default="")):
    # Fails closed: with no token configured, the endpoint can't be
    # triggered by anyone, rather than defaulting to wide open.
    if not settings.ADMIN_RESTART_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Restart endpoint disabled: set ADMIN_RESTART_TOKEN to enable it.",
        )
    if not secrets.compare_digest(x_admin_token, settings.ADMIN_RESTART_TOKEN):
        logger.warning("Rejected backend restart request: invalid admin token.")
        raise HTTPException(status_code=401, detail="Invalid admin token.")

    logger.warning("Backend restart requested via /api/v1/admin/restart-backend")
    background_tasks.add_task(_reexec_process)
    return {"status": "restarting"}
