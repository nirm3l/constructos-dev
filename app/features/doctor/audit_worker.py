from __future__ import annotations

import threading
from typing import Sequence

from sqlalchemy import select

from features.doctor.service import execute_doctor_quick_action
from shared.models import SessionLocal, User, WorkspaceDoctorConfig, WorkspaceMember
from shared.settings import (
    DOCTOR_RUNTIME_CONTRACT_AUDIT_AUTO_ENABLED,
    DOCTOR_RUNTIME_CONTRACT_AUDIT_AUTO_INTERVAL_SECONDS,
    logger,
)

_worker_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def _pick_workspace_admin_user(*, workspace_id: str) -> User | None:
    with SessionLocal() as db:
        rows = db.execute(
            select(User, WorkspaceMember.role.label("member_role"))
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role.in_(("Owner", "Admin")),
                User.is_active == True,  # noqa: E712
            )
        ).all()
    if not rows:
        return None
    role_rank = {"Owner": 0, "Admin": 1}
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            int(role_rank.get(str(getattr(row, "member_role", "") or ""), 99)),
            str(getattr(row[0], "id", "")),
        ),
    )
    first_row = sorted_rows[0]
    user_obj = first_row[0]
    return user_obj if isinstance(user_obj, User) else None


def _target_workspace_ids(explicit_workspace_ids: Sequence[str] | None = None) -> list[str]:
    if explicit_workspace_ids is not None:
        return [str(item or "").strip() for item in explicit_workspace_ids if str(item or "").strip()]
    with SessionLocal() as db:
        rows = db.execute(
            select(WorkspaceDoctorConfig.workspace_id).where(
                WorkspaceDoctorConfig.is_deleted == False,  # noqa: E712
                WorkspaceDoctorConfig.enabled == True,  # noqa: E712
            )
        ).scalars().all()
    unique: list[str] = []
    for raw in rows:
        workspace_id = str(raw or "").strip()
        if not workspace_id or workspace_id in unique:
            continue
        unique.append(workspace_id)
    return unique


def run_doctor_runtime_contract_audit_auto_tick(
    *, explicit_workspace_ids: Sequence[str] | None = None
) -> int:
    if not bool(DOCTOR_RUNTIME_CONTRACT_AUDIT_AUTO_ENABLED):
        return 0

    completed = 0
    for workspace_id in _target_workspace_ids(explicit_workspace_ids):
        admin_user = _pick_workspace_admin_user(workspace_id=workspace_id)
        if admin_user is None:
            continue
        try:
            with SessionLocal() as db:
                execute_doctor_quick_action(
                    db,
                    workspace_id=workspace_id,
                    user=admin_user,
                    action_id="runtime-contract-audit",
                    command_id=f"dr:auto:audit:{workspace_id[:8]}",
                )
            completed += 1
        except Exception as exc:
            logger.warning(
                "Doctor auto runtime-contract-audit tick failed for workspace %s: %s",
                workspace_id,
                exc,
            )
    return completed


def _worker_loop() -> None:
    while not _worker_stop_event.is_set():
        try:
            run_doctor_runtime_contract_audit_auto_tick()
        except Exception as exc:
            logger.warning("Doctor auto runtime-contract-audit worker tick failed: %s", exc)
        _worker_stop_event.wait(max(60.0, float(DOCTOR_RUNTIME_CONTRACT_AUDIT_AUTO_INTERVAL_SECONDS)))


def start_doctor_runtime_contract_audit_worker() -> None:
    global _worker_thread
    if not bool(DOCTOR_RUNTIME_CONTRACT_AUDIT_AUTO_ENABLED):
        return
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="doctor-runtime-contract-audit-worker",
        daemon=True,
    )
    _worker_thread.start()


def stop_doctor_runtime_contract_audit_worker() -> None:
    global _worker_thread
    _worker_stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3)
    _worker_thread = None
