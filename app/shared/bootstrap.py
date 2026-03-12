from __future__ import annotations

import os
import time
import json
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from features.bootstrap.read_models import bootstrap_payload_read_model
from .eventing import append_event, current_version, get_kurrent_client
from features.projects.domain import EVENT_CREATED as PROJECT_EVENT_CREATED
from features.projects.domain import EVENT_UPDATED as PROJECT_EVENT_UPDATED
from features.rules.domain import EVENT_CREATED as PROJECT_RULE_EVENT_CREATED
from features.notes.domain import EVENT_CREATED as NOTE_EVENT_CREATED
from features.specifications.domain import EVENT_CREATED as SPECIFICATION_EVENT_CREATED
from features.tasks.domain import EVENT_CREATED as TASK_EVENT_CREATED
from features.task_groups.domain import EVENT_CREATED as TASK_GROUP_EVENT_CREATED
from features.note_groups.domain import EVENT_CREATED as NOTE_GROUP_EVENT_CREATED
from .auth import generate_temporary_password, hash_password, verify_password
from .licensing import resolve_license_installation_id
from . import models as shared_models
from .models import (
    ContextSessionState,
    EventStormingAnalysisJob,
    EventStormingAnalysisRun,
    Note,
    NoteGroup,
    LicenseInstallation,
    Project,
    ProjectMember,
    ProjectRule,
    ProjectTagIndex,
    Specification,
    Task,
    TaskGroup,
    TaskWatcher,
    User,
    Workspace,
    WorkspaceSkill,
    WorkspaceMember,
)
from .serializers import to_iso_utc
from .settings import (
    CLAUDE_SYSTEM_FULL_NAME,
    CLAUDE_SYSTEM_USER_ID,
    CLAUDE_SYSTEM_USERNAME,
    BOOTSTRAP_PROJECT_ID,
    BOOTSTRAP_PASSWORD,
    BOOTSTRAP_TASK_ID,
    BOOTSTRAP_FULL_NAME,
    BOOTSTRAP_USERNAME,
    BOOTSTRAP_WORKSPACE_ID,
    DEFAULT_USER_ID,
    DEFAULT_STATUSES,
    LEGACY_BOOTSTRAP_PASSWORD,
    LICENSE_TRIAL_DAYS,
    CODEX_SYSTEM_FULL_NAME,
    CODEX_SYSTEM_USER_ID,
    CODEX_SYSTEM_USERNAME,
    logger,
)

_SEED_WORKSPACE_SKILLS_DIR = Path(__file__).resolve().parent / "workspace_skill_seeds"
_SEED_FRONTMATTER_FIELD_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
_SEED_SKILL_KEY_SANITIZER_RE = re.compile(r"[^a-z0-9]+")
_SEED_ALLOWED_MODES = {"advisory", "enforced"}
_SEED_ALLOWED_TRUST_LEVELS = {"reviewed", "untrusted", "verified"}
_DEFAULT_WORKSPACE_SKILLS_CACHE: tuple[dict[str, str], ...] | None = None
_PLUGIN_KEYS_WITHOUT_WORKSPACE_SKILLS = {"team_mode", "git_delivery"}


def _bootstrap_entity_id(kind: str, key: str) -> str:
    seed = f"bootstrap:{BOOTSTRAP_PROJECT_ID}:{kind}:{key}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


BOOTSTRAP_TASK_BOARD_TOUR_ID = _bootstrap_entity_id("task", "board-tour")
BOOTSTRAP_TASK_AUTOMATION_TOUR_ID = _bootstrap_entity_id("task", "automation-tour")
BOOTSTRAP_TASK_KNOWLEDGE_TOUR_ID = _bootstrap_entity_id("task", "knowledge-tour")
BOOTSTRAP_TASK_SPRINT_A_ID = _bootstrap_entity_id("task-group", "sprint-a")
BOOTSTRAP_TASK_SPRINT_B_ID = _bootstrap_entity_id("task-group", "sprint-b")
BOOTSTRAP_NOTE_DISCOVERY_GROUP_ID = _bootstrap_entity_id("note-group", "discovery")
BOOTSTRAP_NOTE_SHIP_GROUP_ID = _bootstrap_entity_id("note-group", "shipping")
BOOTSTRAP_SPEC_DEMO_ID = _bootstrap_entity_id("specification", "demo-spec")
BOOTSTRAP_NOTE_DEMO_ID = _bootstrap_entity_id("note", "demo-note")
BOOTSTRAP_NOTE_EXECUTION_ID = _bootstrap_entity_id("note", "execution-notes")
BOOTSTRAP_NOTE_RELEASE_ID = _bootstrap_entity_id("note", "release-notes")
BOOTSTRAP_RULE_CONTEXT_ID = _bootstrap_entity_id("project-rule", "context-rule")
BOOTSTRAP_RULE_DELIVERY_ID = _bootstrap_entity_id("project-rule", "delivery-rule")
DEMO_PROJECT_NAME = "Demo"
DEMO_PROJECT_STATUSES = ["To do", "In progress", "Done"]
BOOTSTRAP_ES_BOUNDED_CONTEXT_ID = _bootstrap_entity_id("event-storming", "bounded-context-general")
BOOTSTRAP_ES_AGGREGATE_ID = _bootstrap_entity_id("event-storming", "aggregate-general")
BOOTSTRAP_ES_COMMAND_PLAN_ID = _bootstrap_entity_id("event-storming", "command-plan-work")
BOOTSTRAP_ES_COMMAND_EXECUTE_ID = _bootstrap_entity_id("event-storming", "command-execute-work")
BOOTSTRAP_ES_POLICY_ID = _bootstrap_entity_id("event-storming", "policy-quality-gate")
BOOTSTRAP_ES_READ_MODEL_ID = _bootstrap_entity_id("event-storming", "read-model-board")


def _enabled_plugin_keys() -> set[str]:
    from plugins.registry import list_workflow_plugins

    keys: set[str] = set()
    for plugin in list_workflow_plugins():
        key = str(getattr(plugin, "key", "")).strip().lower()
        if key:
            keys.add(key)
    return keys


def _seed_demo_event_storming_scaffold() -> None:
    try:
        from .knowledge_graph import graph_enabled, run_graph_query
    except Exception:
        return
    if not graph_enabled():
        return

    component_labels = ["BoundedContext", "Aggregate", "Command", "DomainEvent", "Policy", "ReadModel"]
    run_graph_query(
        """
        MATCH (n)
        WHERE coalesce(n.project_id, '') = $project_id
          AND any(label IN labels(n) WHERE label IN $component_labels)
        DETACH DELETE n
        """,
        {"project_id": BOOTSTRAP_PROJECT_ID, "component_labels": component_labels},
        write=True,
    )
    run_graph_query(
        """
        MERGE (p:Project {id:$project_id})
        SET p.name = coalesce(p.name, $project_name),
            p.project_id = $project_id
        """,
        {"project_id": BOOTSTRAP_PROJECT_ID, "project_name": DEMO_PROJECT_NAME},
        write=True,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    nodes = [
        ("BoundedContext", BOOTSTRAP_ES_BOUNDED_CONTEXT_ID, "Workspace Delivery Core", "bounded_context"),
        ("Aggregate", BOOTSTRAP_ES_AGGREGATE_ID, "Demo Project Aggregate", "aggregate"),
        ("Command", BOOTSTRAP_ES_COMMAND_PLAN_ID, "Plan Work Item", "command"),
        ("Command", BOOTSTRAP_ES_COMMAND_EXECUTE_ID, "Execute Work Item", "command"),
        ("Policy", BOOTSTRAP_ES_POLICY_ID, "Quality Gate Policy", "policy"),
        ("ReadModel", BOOTSTRAP_ES_READ_MODEL_ID, "Board Snapshot", "read_model"),
    ]
    for label, node_id, name, component_type in nodes:
        run_graph_query(
            f"""
            MERGE (n:{label} {{id:$id}})
            SET n.project_id = $project_id,
                n.workspace_id = $workspace_id,
                n.name = $name,
                n.title = $name,
                n.component_type = $component_type,
                n.updated_at = $updated_at
            """,
            {
                "id": node_id,
                "project_id": BOOTSTRAP_PROJECT_ID,
                "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                "name": name,
                "component_type": component_type,
                "updated_at": now_iso,
            },
            write=True,
        )
        run_graph_query(
            f"""
            MATCH (p:Project {{id:$project_id}})
            MATCH (n:{label} {{id:$id}})
            MERGE (p)-[:CONTAINS_ES]->(n)
            """,
            {"project_id": BOOTSTRAP_PROJECT_ID, "id": node_id},
            write=True,
        )

    edges = [
        (BOOTSTRAP_ES_BOUNDED_CONTEXT_ID, "CONTAINS", BOOTSTRAP_ES_AGGREGATE_ID),
        (BOOTSTRAP_ES_COMMAND_PLAN_ID, "TARGETS", BOOTSTRAP_ES_AGGREGATE_ID),
        (BOOTSTRAP_ES_COMMAND_EXECUTE_ID, "TARGETS", BOOTSTRAP_ES_AGGREGATE_ID),
        (BOOTSTRAP_ES_POLICY_ID, "GUARDS", BOOTSTRAP_ES_COMMAND_EXECUTE_ID),
        (BOOTSTRAP_ES_READ_MODEL_ID, "READS_FROM", BOOTSTRAP_ES_AGGREGATE_ID),
    ]
    for source_id, relation, target_id in edges:
        run_graph_query(
            f"""
            MATCH (a {{id:$source_id}})
            MATCH (b {{id:$target_id}})
            MERGE (a)-[:{relation}]->(b)
            """,
            {"source_id": source_id, "target_id": target_id},
            write=True,
        )


def _seed_workspace_skill_dirs() -> list[Path]:
    dirs: list[Path] = []
    if _SEED_WORKSPACE_SKILLS_DIR.is_dir():
        dirs.append(_SEED_WORKSPACE_SKILLS_DIR)
    plugin_keys = _enabled_plugin_keys()
    plugins_root = Path(__file__).resolve().parents[1] / "plugins"
    for plugin_key in sorted(plugin_keys):
        if plugin_key in _PLUGIN_KEYS_WITHOUT_WORKSPACE_SKILLS:
            continue
        plugin_seed_dir = plugins_root / plugin_key / "workspace_skill_seeds"
        if plugin_seed_dir.is_dir():
            dirs.append(plugin_seed_dir)
    return dirs


def _normalize_seed_frontmatter_value(value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    return normalized


def _parse_seed_skill_file(text: str, *, source_name: str) -> tuple[dict[str, str], str]:
    raw_text = str(text or "")
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{source_name}: expected frontmatter block starting with '---'")

    end_index = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index < 0:
        raise ValueError(f"{source_name}: frontmatter block is missing closing '---'")

    metadata: dict[str, str] = {}
    for raw_line in lines[1:end_index]:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _SEED_FRONTMATTER_FIELD_RE.match(stripped)
        if not match:
            raise ValueError(f"{source_name}: invalid frontmatter line '{stripped}'")
        key = str(match.group(1) or "").strip().lower()
        value = _normalize_seed_frontmatter_value(match.group(2))
        if key:
            metadata[key] = value

    content = "\n".join(lines[end_index + 1:]).strip()
    if not content:
        raise ValueError(f"{source_name}: content is empty")
    return metadata, content


def _normalize_seed_skill_key(raw: str, *, source_name: str) -> str:
    candidate = str(raw or "").strip().lower()
    candidate = _SEED_SKILL_KEY_SANITIZER_RE.sub("_", candidate).strip("_")
    candidate = candidate[:128].strip("_")
    if not candidate:
        raise ValueError(f"{source_name}: skill_key cannot be empty")
    return candidate


def _extract_seed_heading(content: str) -> str:
    for line in str(content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading[:160]
    return ""


def _extract_seed_summary(content: str) -> str:
    for line in str(content or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        return stripped[:400]
    return ""


def _load_default_workspace_skills() -> tuple[dict[str, str], ...]:
    seed_dirs = _seed_workspace_skill_dirs()
    if not seed_dirs:
        raise RuntimeError("No workspace skill seed directories found.")

    seed_files: list[Path] = []
    for seed_dir in seed_dirs:
        seed_files.extend(sorted(seed_dir.glob("*.md")))
    if not seed_files:
        raise RuntimeError("No workspace skill seed files found in configured seed directories.")

    loaded: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for seed_file in seed_files:
        metadata, content = _parse_seed_skill_file(seed_file.read_text(encoding="utf-8"), source_name=seed_file.name)
        skill_key = _normalize_seed_skill_key(metadata.get("skill_key", ""), source_name=seed_file.name)
        if skill_key in seen_keys:
            raise RuntimeError(f"Duplicate workspace skill_key '{skill_key}' in seed file {seed_file.name}")
        seen_keys.add(skill_key)

        name = str(metadata.get("name") or metadata.get("title") or "").strip() or _extract_seed_heading(content)
        if not name:
            raise RuntimeError(f"{seed_file.name}: name/title is required")

        summary = str(metadata.get("summary") or metadata.get("description") or "").strip() or _extract_seed_summary(content)
        if not summary:
            raise RuntimeError(f"{seed_file.name}: summary/description is required")

        mode = str(metadata.get("mode") or "advisory").strip().lower()
        if mode not in _SEED_ALLOWED_MODES:
            allowed = ", ".join(sorted(_SEED_ALLOWED_MODES))
            raise RuntimeError(f"{seed_file.name}: mode must be one of: {allowed}")

        trust_level = str(metadata.get("trust_level") or "verified").strip().lower()
        if trust_level not in _SEED_ALLOWED_TRUST_LEVELS:
            allowed = ", ".join(sorted(_SEED_ALLOWED_TRUST_LEVELS))
            raise RuntimeError(f"{seed_file.name}: trust_level must be one of: {allowed}")

        source_locator = str(metadata.get("source_locator") or f"seed://workspace-skills/{skill_key.replace('_', '-')}").strip()
        loaded.append(
            {
                "skill_key": skill_key,
                "name": name,
                "summary": summary,
                "source_locator": source_locator,
                "mode": mode,
                "trust_level": trust_level,
                "content": content.strip(),
            }
        )

    return tuple(loaded)


def _get_default_workspace_skills() -> tuple[dict[str, str], ...]:
    global _DEFAULT_WORKSPACE_SKILLS_CACHE
    if _DEFAULT_WORKSPACE_SKILLS_CACHE is None:
        _DEFAULT_WORKSPACE_SKILLS_CACHE = _load_default_workspace_skills()
    return _DEFAULT_WORKSPACE_SKILLS_CACHE


def ensure_system_users(db: Session):
    for user_id, username, full_name in (
        (CODEX_SYSTEM_USER_ID, CODEX_SYSTEM_USERNAME, CODEX_SYSTEM_FULL_NAME),
        (CLAUDE_SYSTEM_USER_ID, CLAUDE_SYSTEM_USERNAME, CLAUDE_SYSTEM_FULL_NAME),
    ):
        if not db.get(User, user_id):
            db.add(
                User(
                    id=user_id,
                    username=username,
                    full_name=full_name,
                    user_type="agent",
                    password_hash=None,
                    must_change_password=False,
                    password_changed_at=None,
                    is_active=True,
                    timezone="UTC",
                    theme="dark",
                )
            )
            continue
        agent_user = db.get(User, user_id)
        if agent_user:
            if agent_user.username != username:
                agent_user.username = username
            if agent_user.full_name != full_name:
                agent_user.full_name = full_name
            if agent_user.user_type != "agent":
                agent_user.user_type = "agent"
            # System agents do not authenticate with username/password.
            agent_user.password_hash = None
            agent_user.must_change_password = False
            agent_user.password_changed_at = None
            agent_user.is_active = True
    workspace = db.get(Workspace, BOOTSTRAP_WORKSPACE_ID)
    if workspace:
        for user_id in (CODEX_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID):
            membership = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == BOOTSTRAP_WORKSPACE_ID,
                    WorkspaceMember.user_id == user_id,
                )
            ).scalar_one_or_none()
            if not membership:
                db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=user_id, role="Admin"))
            elif membership.role not in {"Owner", "Admin"}:
                membership.role = "Admin"
    db.commit()


def ensure_non_human_workspace_admin_roles(db: Session):
    memberships = db.execute(
        select(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(User.user_type != "human")
    ).scalars().all()
    changed = False
    for membership in memberships:
        if membership.role in {"Owner", "Admin"}:
            continue
        membership.role = "Admin"
        changed = True
    if changed:
        db.commit()


def ensure_workspace_skill_catalog_seed(db: Session, *, workspace_id: str, actor_user_id: str):
    changed = False
    imported_at = datetime.now(timezone.utc).isoformat()
    for default_skill in _get_default_workspace_skills():
        skill_key = str(default_skill["skill_key"])
        existing = db.execute(
            select(WorkspaceSkill).where(
                WorkspaceSkill.workspace_id == workspace_id,
                WorkspaceSkill.skill_key == skill_key,
            )
        ).scalar_one_or_none()
        manifest = {
            "seeded_default": True,
            "imported_at": imported_at,
            "source_content": str(default_skill["content"]),
            "source_content_sha256": "",
            "source_locator": str(default_skill["source_locator"]),
        }
        manifest["source_content_sha256"] = hashlib.sha256(
            str(manifest["source_content"]).encode("utf-8")
        ).hexdigest()
        if existing is None:
            db.add(
                WorkspaceSkill(
                    workspace_id=workspace_id,
                    skill_key=skill_key,
                    name=str(default_skill["name"]),
                    summary=str(default_skill["summary"]),
                    source_type="seed",
                    source_locator=str(default_skill["source_locator"]),
                    source_version=None,
                    trust_level=str(default_skill["trust_level"]),
                    mode=str(default_skill["mode"]),
                    manifest_json=json.dumps(manifest, ensure_ascii=True, sort_keys=True),
                    is_seeded=True,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                    is_deleted=False,
                )
            )
            changed = True
            continue
        if bool(existing.is_deleted):
            existing.is_deleted = False
            existing.is_seeded = True
            existing.updated_by = actor_user_id
            if not str(existing.manifest_json or "").strip():
                existing.manifest_json = json.dumps(manifest, ensure_ascii=True, sort_keys=True)
            changed = True
            continue

        # Keep seeded catalog entries in sync with current seed files.
        desired_name = str(default_skill["name"])
        desired_summary = str(default_skill["summary"])
        desired_source_locator = str(default_skill["source_locator"])
        desired_mode = str(default_skill["mode"])
        desired_trust = str(default_skill["trust_level"])
        desired_manifest_json = json.dumps(manifest, ensure_ascii=True, sort_keys=True)
        if (
            str(existing.name or "") != desired_name
            or str(existing.summary or "") != desired_summary
            or str(existing.source_type or "") != "seed"
            or str(existing.source_locator or "") != desired_source_locator
            or str(existing.mode or "") != desired_mode
            or str(existing.trust_level or "") != desired_trust
            or str(existing.manifest_json or "") != desired_manifest_json
            or not bool(existing.is_seeded)
            or bool(existing.is_deleted)
        ):
            existing.name = desired_name
            existing.summary = desired_summary
            existing.source_type = "seed"
            existing.source_locator = desired_source_locator
            existing.mode = desired_mode
            existing.trust_level = desired_trust
            existing.manifest_json = desired_manifest_json
            existing.is_seeded = True
            existing.is_deleted = False
            existing.updated_by = actor_user_id
            changed = True
    if changed:
        db.commit()


def ensure_user_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("users")}
    if "user_type" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN user_type VARCHAR(16) DEFAULT 'human'"))
    if "password_hash" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)"))
    if "must_change_password" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT TRUE"))
    if "password_changed_at" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP WITH TIME ZONE"))
    if "is_active" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
    if "agent_chat_model" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN agent_chat_model VARCHAR(128) DEFAULT ''"))
    if "agent_chat_reasoning_effort" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN agent_chat_reasoning_effort VARCHAR(16) DEFAULT 'medium'"))
    if "onboarding_quick_tour_completed" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN onboarding_quick_tour_completed BOOLEAN DEFAULT FALSE"))
    if "onboarding_advanced_tour_completed" not in existing:
        db.execute(text("ALTER TABLE users ADD COLUMN onboarding_advanced_tour_completed BOOLEAN DEFAULT FALSE"))
    db.execute(text("UPDATE users SET user_type='human' WHERE user_type IS NULL OR user_type = ''"))
    db.execute(
        text("UPDATE users SET user_type='agent' WHERE id IN (:codex_agent_id, :claude_agent_id)"),
        {"codex_agent_id": CODEX_SYSTEM_USER_ID, "claude_agent_id": CLAUDE_SYSTEM_USER_ID},
    )
    db.execute(text("UPDATE users SET must_change_password=TRUE WHERE must_change_password IS NULL"))
    db.execute(text("UPDATE users SET is_active=TRUE WHERE is_active IS NULL"))
    db.execute(text("UPDATE users SET agent_chat_model='' WHERE agent_chat_model IS NULL"))
    db.execute(
        text(
            "UPDATE users SET agent_chat_reasoning_effort='medium' "
            "WHERE agent_chat_reasoning_effort IS NULL OR agent_chat_reasoning_effort = ''"
        )
    )
    db.execute(
        text("UPDATE users SET onboarding_quick_tour_completed=FALSE WHERE onboarding_quick_tour_completed IS NULL")
    )
    db.execute(
        text("UPDATE users SET onboarding_advanced_tour_completed=FALSE WHERE onboarding_advanced_tour_completed IS NULL")
    )
    db.commit()


def ensure_user_password_defaults(db: Session):
    default_user = db.get(User, DEFAULT_USER_ID)
    if default_user:
        default_user_username = str(default_user.username or "").strip()
        default_user_full_name = str(default_user.full_name or "").strip()
        default_user_password_hash = str(default_user.password_hash or "").strip()

        if default_user_username in {"", "m4tr1x"} and default_user.username != BOOTSTRAP_USERNAME:
            default_user.username = BOOTSTRAP_USERNAME
        if default_user_full_name in {"", "m4tr1x"} and default_user.full_name != BOOTSTRAP_FULL_NAME:
            default_user.full_name = BOOTSTRAP_FULL_NAME

        should_reset_password = False
        if not default_user_password_hash:
            should_reset_password = True
        elif verify_password(LEGACY_BOOTSTRAP_PASSWORD, default_user_password_hash) and (
            not verify_password(BOOTSTRAP_PASSWORD, default_user_password_hash)
        ):
            should_reset_password = True

        if should_reset_password:
            default_user.password_hash = hash_password(BOOTSTRAP_PASSWORD)
            default_user.must_change_password = False
            default_user.password_changed_at = datetime.now(timezone.utc)
        default_user.is_active = True

    legacy_users = db.execute(
        select(User).where(
            User.id != DEFAULT_USER_ID,
            User.user_type == "human",
            User.password_hash.is_(None),
        )
    ).scalars().all()
    for user in legacy_users:
        user.password_hash = hash_password(generate_temporary_password(12))
        user.must_change_password = True
        user.is_active = True
        user.password_changed_at = None

    # Non-human users (agent/bot/service) should not carry password state.
    non_human_users = db.execute(
        select(User).where(User.user_type != "human")
    ).scalars().all()
    for user in non_human_users:
        user.password_hash = None
        user.must_change_password = False
        user.password_changed_at = None
        user.is_active = True

    db.commit()


def ensure_task_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("tasks")}
    required_columns = {
        "instruction": "ALTER TABLE tasks ADD COLUMN instruction TEXT",
        "execution_triggers": "ALTER TABLE tasks ADD COLUMN execution_triggers TEXT DEFAULT '[]'",
        "task_relationships": "ALTER TABLE tasks ADD COLUMN task_relationships TEXT DEFAULT '[]'",
        "task_type": "ALTER TABLE tasks ADD COLUMN task_type VARCHAR(32) DEFAULT 'manual'",
        "scheduled_instruction": "ALTER TABLE tasks ADD COLUMN scheduled_instruction TEXT",
        "scheduled_at_utc": "ALTER TABLE tasks ADD COLUMN scheduled_at_utc TIMESTAMP WITH TIME ZONE",
        "schedule_timezone": "ALTER TABLE tasks ADD COLUMN schedule_timezone VARCHAR(64)",
        "schedule_state": "ALTER TABLE tasks ADD COLUMN schedule_state VARCHAR(16) DEFAULT 'idle'",
        "last_schedule_run_at": "ALTER TABLE tasks ADD COLUMN last_schedule_run_at TIMESTAMP WITH TIME ZONE",
        "last_schedule_error": "ALTER TABLE tasks ADD COLUMN last_schedule_error TEXT",
        "external_refs": "ALTER TABLE tasks ADD COLUMN external_refs TEXT DEFAULT '[]'",
        "attachment_refs": "ALTER TABLE tasks ADD COLUMN attachment_refs TEXT DEFAULT '[]'",
        "specification_id": "ALTER TABLE tasks ADD COLUMN specification_id VARCHAR(36)",
        "assigned_agent_code": "ALTER TABLE tasks ADD COLUMN assigned_agent_code VARCHAR(64)",
    }
    for column, ddl in required_columns.items():
        if column not in existing:
            db.execute(text(ddl))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_assigned_agent_code ON tasks(assigned_agent_code)"))
    db.commit()


def ensure_task_group_tables(db: Session):
    TaskGroup.__table__.create(bind=db.bind, checkfirst=True)
    existing_task_columns = {column["name"] for column in inspect(db.bind).get_columns("tasks")}
    if "task_group_id" not in existing_task_columns:
        db.execute(text("ALTER TABLE tasks ADD COLUMN task_group_id VARCHAR(36)"))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_task_groups_project_name ON task_groups(project_id, name)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_task_groups_workspace_id ON task_groups(workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_task_groups_project_id ON task_groups(project_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_task_group_id ON tasks(task_group_id)"))
    db.commit()


def ensure_note_group_tables(db: Session):
    NoteGroup.__table__.create(bind=db.bind, checkfirst=True)
    existing_note_columns = {column["name"] for column in inspect(db.bind).get_columns("notes")}
    if "note_group_id" not in existing_note_columns:
        db.execute(text("ALTER TABLE notes ADD COLUMN note_group_id VARCHAR(36)"))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_note_groups_project_name ON note_groups(project_id, name)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_note_groups_workspace_id ON note_groups(workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_note_groups_project_id ON note_groups(project_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notes_note_group_id ON notes(note_group_id)"))
    db.commit()


def ensure_saved_view_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("saved_views")}
    if "project_id" not in existing:
        db.execute(text("ALTER TABLE saved_views ADD COLUMN project_id VARCHAR(36)"))
    db.commit()


def ensure_project_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("projects")}
    if "external_refs" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN external_refs TEXT DEFAULT '[]'"))
    if "attachment_refs" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN attachment_refs TEXT DEFAULT '[]'"))
    if "embedding_enabled" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN embedding_enabled BOOLEAN DEFAULT FALSE"))
    if "embedding_model" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN embedding_model VARCHAR(128)"))
    if "context_pack_evidence_top_k" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN context_pack_evidence_top_k INTEGER"))
    if "automation_max_parallel_tasks" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN automation_max_parallel_tasks INTEGER DEFAULT 4"))
    if "chat_index_mode" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN chat_index_mode VARCHAR(32) DEFAULT 'OFF'"))
    if "chat_attachment_ingestion_mode" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN chat_attachment_ingestion_mode VARCHAR(32) DEFAULT 'METADATA_ONLY'"))
    if "event_storming_enabled" not in existing:
        db.execute(text("ALTER TABLE projects ADD COLUMN event_storming_enabled BOOLEAN DEFAULT TRUE"))
    db.execute(text("UPDATE projects SET chat_index_mode='OFF' WHERE chat_index_mode IS NULL OR chat_index_mode = ''"))
    db.execute(
        text(
            "UPDATE projects SET chat_attachment_ingestion_mode='METADATA_ONLY' "
            "WHERE chat_attachment_ingestion_mode IS NULL OR chat_attachment_ingestion_mode = ''"
        )
    )
    db.execute(
        text(
            "UPDATE projects SET event_storming_enabled=TRUE "
            "WHERE event_storming_enabled IS NULL"
        )
    )
    db.execute(
        text(
            "UPDATE projects SET automation_max_parallel_tasks=4 "
            "WHERE automation_max_parallel_tasks IS NULL OR automation_max_parallel_tasks < 1"
        )
    )
    db.commit()


def ensure_event_storming_analysis_table_columns(db: Session):
    EventStormingAnalysisJob.__table__.create(bind=db.bind, checkfirst=True)
    EventStormingAnalysisRun.__table__.create(bind=db.bind, checkfirst=True)
    existing = {column["name"] for column in inspect(db.bind).get_columns("event_storming_analysis_runs")}
    if "prompt_chars" not in existing:
        db.execute(text("ALTER TABLE event_storming_analysis_runs ADD COLUMN prompt_chars INTEGER DEFAULT 0"))
    if "input_hash" not in existing:
        db.execute(text("ALTER TABLE event_storming_analysis_runs ADD COLUMN input_hash VARCHAR(64)"))
    if "usage_json" not in existing:
        db.execute(text("ALTER TABLE event_storming_analysis_runs ADD COLUMN usage_json TEXT DEFAULT '{}'"))
    db.execute(
        text("CREATE INDEX IF NOT EXISTS ix_event_storming_analysis_runs_input_hash ON event_storming_analysis_runs(input_hash)")
    )
    db.execute(
        text("UPDATE event_storming_analysis_runs SET usage_json='{}' WHERE usage_json IS NULL OR usage_json = ''")
    )
    db.commit()


def ensure_context_session_state_table_columns(db: Session):
    ContextSessionState.__table__.create(bind=db.bind, checkfirst=True)
    db.commit()


def ensure_note_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("notes")}
    if "external_refs" not in existing:
        db.execute(text("ALTER TABLE notes ADD COLUMN external_refs TEXT DEFAULT '[]'"))
    if "attachment_refs" not in existing:
        db.execute(text("ALTER TABLE notes ADD COLUMN attachment_refs TEXT DEFAULT '[]'"))
    if "specification_id" not in existing:
        db.execute(text("ALTER TABLE notes ADD COLUMN specification_id VARCHAR(36)"))
    db.commit()


def ensure_specification_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("specifications")}
    if "tags" not in existing:
        db.execute(text("ALTER TABLE specifications ADD COLUMN tags TEXT DEFAULT '[]'"))
    db.commit()


def ensure_notification_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("notifications")}
    if "workspace_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN workspace_id VARCHAR(36)"))
    if "project_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN project_id VARCHAR(36)"))
    if "task_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN task_id VARCHAR(36)"))
    if "note_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN note_id VARCHAR(36)"))
    if "specification_id" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN specification_id VARCHAR(36)"))
    if "notification_type" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN notification_type VARCHAR(64)"))
    if "severity" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN severity VARCHAR(16)"))
    if "dedupe_key" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN dedupe_key VARCHAR(255)"))
    if "payload_json" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN payload_json TEXT"))
    if "source_event" not in existing:
        db.execute(text("ALTER TABLE notifications ADD COLUMN source_event VARCHAR(128)"))
    db.execute(text("UPDATE notifications SET notification_type='Legacy' WHERE notification_type IS NULL OR notification_type = ''"))
    db.execute(text("UPDATE notifications SET severity='info' WHERE severity IS NULL OR severity = ''"))
    db.execute(text("UPDATE notifications SET payload_json='{}' WHERE payload_json IS NULL OR payload_json = ''"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_workspace_id ON notifications(workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_project_id ON notifications(project_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_task_id ON notifications(task_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_note_id ON notifications(note_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_specification_id ON notifications(specification_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_user_created_at ON notifications(user_id, created_at)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_user_dedupe_created_at ON notifications(user_id, dedupe_key, created_at)"))
    db.commit()


def ensure_task_comment_table_columns(db: Session):
    existing = {column["name"] for column in inspect(db.bind).get_columns("task_comments")}
    if "event_version" not in existing:
        db.execute(text("ALTER TABLE task_comments ADD COLUMN event_version INTEGER"))
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_task_comments_task_event_version ON task_comments(task_id, event_version)"))
    db.commit()


def ensure_chat_table_columns(db: Session):
    existing_sessions = {column["name"] for column in inspect(db.bind).get_columns("chat_sessions")}
    if "session_attachment_refs" not in existing_sessions:
        db.execute(text("ALTER TABLE chat_sessions ADD COLUMN session_attachment_refs TEXT DEFAULT '[]'"))
    db.execute(
        text(
            "UPDATE chat_sessions SET session_attachment_refs='[]' "
            "WHERE session_attachment_refs IS NULL OR session_attachment_refs = ''"
        )
    )
    db.commit()


def ensure_task_watcher_table_constraints(db: Session):
    duplicates = db.execute(
        select(TaskWatcher.task_id, TaskWatcher.user_id)
        .group_by(TaskWatcher.task_id, TaskWatcher.user_id)
        .having(func.count(TaskWatcher.id) > 1)
    ).all()
    for task_id, user_id in duplicates:
        rows = db.execute(
            select(TaskWatcher)
            .where(TaskWatcher.task_id == task_id, TaskWatcher.user_id == user_id)
            .order_by(TaskWatcher.id.asc())
        ).scalars().all()
        for row in rows[1:]:
            db.delete(row)
    db.flush()
    db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_task_watchers_task_user ON task_watchers(task_id, user_id)"))
    db.commit()


def ensure_license_installation(db: Session):
    installation_id = resolve_license_installation_id(db)
    installation = db.execute(
        select(LicenseInstallation).where(LicenseInstallation.installation_id == installation_id)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    trial_days = max(1, int(LICENSE_TRIAL_DAYS))
    if installation is None:
        db.add(
            LicenseInstallation(
                installation_id=installation_id,
                workspace_id=None,
                status="trial",
                plan_code="trial",
                activated_at=now,
                trial_ends_at=now + timedelta(days=trial_days),
                metadata_json='{"source":"bootstrap-local"}',
            )
        )
        db.commit()
        return
    changed = False
    if installation.workspace_id is None and db.get(Workspace, BOOTSTRAP_WORKSPACE_ID) is not None:
        installation.workspace_id = BOOTSTRAP_WORKSPACE_ID
        changed = True
    if installation.activated_at is None:
        installation.activated_at = now
        changed = True
    if installation.trial_ends_at is None:
        installation.trial_ends_at = now + timedelta(days=trial_days)
        changed = True
    if changed:
        db.commit()


def bootstrap_data():
    shared_models.ensure_engine()
    shared_models.Base.metadata.create_all(bind=shared_models.engine)
    with shared_models.SessionLocal() as db:
        ensure_user_table_columns(db)
        ensure_project_table_columns(db)
        ensure_note_table_columns(db)
        ensure_note_group_tables(db)
        ensure_specification_table_columns(db)
        ensure_notification_table_columns(db)
        ensure_task_table_columns(db)
        ensure_task_group_tables(db)
        ensure_saved_view_table_columns(db)
        ensure_task_comment_table_columns(db)
        ensure_chat_table_columns(db)
        ensure_event_storming_analysis_table_columns(db)
        ensure_context_session_state_table_columns(db)
        ensure_task_watcher_table_constraints(db)
        ensure_system_users(db)
        default_user = db.get(User, DEFAULT_USER_ID)
        if not default_user:
            db.add_all(
                [
                    User(
                        id=DEFAULT_USER_ID,
                        username=BOOTSTRAP_USERNAME,
                        full_name=BOOTSTRAP_FULL_NAME,
                        user_type="human",
                        password_hash=hash_password(BOOTSTRAP_PASSWORD),
                        must_change_password=False,
                        password_changed_at=datetime.now(timezone.utc),
                        is_active=True,
                        timezone="Europe/Sarajevo",
                        theme="light",
                        agent_chat_model="",
                        agent_chat_reasoning_effort="medium",
                        onboarding_quick_tour_completed=False,
                        onboarding_advanced_tour_completed=False,
                    ),
                    Workspace(id=BOOTSTRAP_WORKSPACE_ID, name="My Workspace", type="team"),
                ]
            )
            db.add_all(
                [
                    WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=DEFAULT_USER_ID, role="Owner"),
                    WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=CODEX_SYSTEM_USER_ID, role="Admin"),
                    WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=CLAUDE_SYSTEM_USER_ID, role="Admin"),
                ]
            )
            db.commit()
        else:
            # Ensure workspace + membership even if app.db was persisted.
            if not db.get(Workspace, BOOTSTRAP_WORKSPACE_ID):
                db.add(Workspace(id=BOOTSTRAP_WORKSPACE_ID, name="My Workspace", type="team"))
                db.commit()
            owner = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == BOOTSTRAP_WORKSPACE_ID,
                    WorkspaceMember.user_id == DEFAULT_USER_ID,
                )
            ).scalar_one_or_none()
            if not owner:
                db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=DEFAULT_USER_ID, role="Owner"))
            for user_id in (CODEX_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID):
                agent_member = db.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == BOOTSTRAP_WORKSPACE_ID,
                        WorkspaceMember.user_id == user_id,
                    )
                ).scalar_one_or_none()
                if not agent_member:
                    db.add(WorkspaceMember(workspace_id=BOOTSTRAP_WORKSPACE_ID, user_id=user_id, role="Admin"))
                elif agent_member.role not in {"Owner", "Admin"}:
                    agent_member.role = "Admin"
            db.commit()

        ensure_license_installation(db)
        ensure_user_password_defaults(db)
        ensure_non_human_workspace_admin_roles(db)
        workspace_ids = db.execute(select(Workspace.id).where(Workspace.is_deleted == False)).scalars().all()
        for workspace_id in workspace_ids:
            ensure_workspace_skill_catalog_seed(
                db,
                workspace_id=str(workspace_id),
                actor_user_id=DEFAULT_USER_ID,
            )

        if current_version(db, "Project", BOOTSTRAP_PROJECT_ID) == 0:
            append_event(
                db,
                aggregate_type="Project",
                aggregate_id=BOOTSTRAP_PROJECT_ID,
                event_type=PROJECT_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "name": DEMO_PROJECT_NAME,
                    "description": "Welcome demo project. Explore tasks, notes, specs, context, and delivery checks.",
                    "custom_statuses": DEMO_PROJECT_STATUSES,
                    "external_refs": [
                        {"url": "https://github.com/nirm3l/constructos", "title": "Constructos repository"},
                        {"url": "https://mermaid.js.org/syntax/flowchart.html", "title": "Mermaid flowchart docs"},
                    ],
                    "attachment_refs": [],
                    "embedding_enabled": True,
                    "event_storming_enabled": False,
                    "chat_index_mode": "OFF",
                    "chat_attachment_ingestion_mode": "METADATA_ONLY",
                },
                metadata={"actor_id": DEFAULT_USER_ID, "workspace_id": BOOTSTRAP_WORKSPACE_ID, "project_id": BOOTSTRAP_PROJECT_ID},
                expected_version=0,
            )
        else:
            general_project = db.get(Project, BOOTSTRAP_PROJECT_ID)
            if general_project is not None:
                version = current_version(db, "Project", BOOTSTRAP_PROJECT_ID)
                payload: dict[str, Any] = {}
                updated_fields: list[str] = []
                if not bool(general_project.embedding_enabled):
                    payload["embedding_enabled"] = True
                    updated_fields.append("embedding_enabled")
                if bool(getattr(general_project, "event_storming_enabled", True)):
                    payload["event_storming_enabled"] = False
                    updated_fields.append("event_storming_enabled")
                if str(general_project.description or "").strip() == "Default project":
                    payload["description"] = "Welcome demo project. Explore tasks, notes, specs, context, and delivery checks."
                    updated_fields.append("description")
                if str(general_project.name or "").strip() == "General":
                    payload["name"] = DEMO_PROJECT_NAME
                    updated_fields.append("name")
                try:
                    current_statuses = json.loads(general_project.custom_statuses or "[]")
                except Exception:
                    current_statuses = []
                if current_statuses != DEMO_PROJECT_STATUSES:
                    payload["custom_statuses"] = DEMO_PROJECT_STATUSES
                    updated_fields.append("custom_statuses")
                if updated_fields:
                    payload["updated_fields"] = updated_fields
                    append_event(
                        db,
                        aggregate_type="Project",
                        aggregate_id=BOOTSTRAP_PROJECT_ID,
                        event_type=PROJECT_EVENT_UPDATED,
                        payload=payload,
                        metadata={
                            "actor_id": DEFAULT_USER_ID,
                            "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                            "project_id": BOOTSTRAP_PROJECT_ID,
                        },
                        expected_version=version,
                    )
        # Ensure project row exists before inserting FK-constrained groups.
        db.commit()

        if current_version(db, "TaskGroup", BOOTSTRAP_TASK_SPRINT_A_ID) == 0:
            append_event(
                db,
                aggregate_type="TaskGroup",
                aggregate_id=BOOTSTRAP_TASK_SPRINT_A_ID,
                event_type=TASK_GROUP_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "name": "Sprint 1 - Product Core",
                    "description": "Core flow and UI baseline for first successful demo.",
                    "color": "#14b8a6",
                    "order_index": 1,
                    "is_deleted": False,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_group_id": BOOTSTRAP_TASK_SPRINT_A_ID,
                },
                expected_version=0,
            )
        if current_version(db, "TaskGroup", BOOTSTRAP_TASK_SPRINT_B_ID) == 0:
            append_event(
                db,
                aggregate_type="TaskGroup",
                aggregate_id=BOOTSTRAP_TASK_SPRINT_B_ID,
                event_type=TASK_GROUP_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "name": "Sprint 2 - Delivery and QA",
                    "description": "Verification, delivery readiness, and rollout polish.",
                    "color": "#f59e0b",
                    "order_index": 2,
                    "is_deleted": False,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_group_id": BOOTSTRAP_TASK_SPRINT_B_ID,
                },
                expected_version=0,
            )
        if current_version(db, "NoteGroup", BOOTSTRAP_NOTE_DISCOVERY_GROUP_ID) == 0:
            append_event(
                db,
                aggregate_type="NoteGroup",
                aggregate_id=BOOTSTRAP_NOTE_DISCOVERY_GROUP_ID,
                event_type=NOTE_GROUP_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "name": "Discovery",
                    "description": "Product context and planning notes.",
                    "color": "#22c55e",
                    "order_index": 1,
                    "is_deleted": False,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_group_id": BOOTSTRAP_NOTE_DISCOVERY_GROUP_ID,
                },
                expected_version=0,
            )
        if current_version(db, "NoteGroup", BOOTSTRAP_NOTE_SHIP_GROUP_ID) == 0:
            append_event(
                db,
                aggregate_type="NoteGroup",
                aggregate_id=BOOTSTRAP_NOTE_SHIP_GROUP_ID,
                event_type=NOTE_GROUP_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "name": "Shiproom",
                    "description": "Release readiness notes and verification records.",
                    "color": "#0ea5e9",
                    "order_index": 2,
                    "is_deleted": False,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_group_id": BOOTSTRAP_NOTE_SHIP_GROUP_ID,
                },
                expected_version=0,
            )

        if current_version(db, "ProjectRule", BOOTSTRAP_RULE_CONTEXT_ID) == 0:
            append_event(
                db,
                aggregate_type="ProjectRule",
                aggregate_id=BOOTSTRAP_RULE_CONTEXT_ID,
                event_type=PROJECT_RULE_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "title": "Keep updates explicit",
                    "body": "When moving a task to a new status, add one concise comment: what changed and what is next.",
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "project_rule_id": BOOTSTRAP_RULE_CONTEXT_ID,
                },
                expected_version=0,
            )
        if current_version(db, "ProjectRule", BOOTSTRAP_RULE_DELIVERY_ID) == 0:
            append_event(
                db,
                aggregate_type="ProjectRule",
                aggregate_id=BOOTSTRAP_RULE_DELIVERY_ID,
                event_type=PROJECT_RULE_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "title": "Definition of done (demo)",
                    "body": "Done means acceptance criteria verified, evidence attached, and activity log updated.",
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "project_rule_id": BOOTSTRAP_RULE_DELIVERY_ID,
                },
                expected_version=0,
            )

        if current_version(db, "Specification", BOOTSTRAP_SPEC_DEMO_ID) == 0:
            append_event(
                db,
                aggregate_type="Specification",
                aggregate_id=BOOTSTRAP_SPEC_DEMO_ID,
                event_type=SPECIFICATION_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "title": "Demo: Product Delivery Flow",
                    "body": (
                        "# Demo specification\n\n"
                        "This item demonstrates markdown rendering with Mermaid and JSON blocks.\n\n"
                        "## Delivery flow\n\n"
                        "```mermaid\n"
                        "flowchart LR\n"
                        "  Idea[Idea] --> Spec[Specification]\n"
                        "  Spec --> Dev[Implementation]\n"
                        "  Dev --> QA[Verification]\n"
                        "  QA --> Ship[Release]\n"
                        "```\n\n"
                        "## Event storming snapshot (static)\n\n"
                        "This diagram is pre-seeded markdown content and does not invoke LLM processing.\n\n"
                        "```mermaid\n"
                        "flowchart LR\n"
                        "  classDef cmd fill:#1f2937,color:#f9fafb,stroke:#9ca3af;\n"
                        "  classDef evt fill:#065f46,color:#ecfdf5,stroke:#34d399;\n"
                        "  classDef pol fill:#7c2d12,color:#fff7ed,stroke:#fb923c;\n"
                        "  classDef actor fill:#0c4a6e,color:#e0f2fe,stroke:#38bdf8;\n"
                        "\n"
                        "  PM([Product]):::actor --> C1[Define acceptance criteria]:::cmd\n"
                        "  C1 --> E1((Specification created)):::evt\n"
                        "  E1 --> C2[Start implementation]:::cmd\n"
                        "  C2 --> E2((Code committed)):::evt\n"
                        "  E2 --> P1{Policy: required checks pass}:::pol\n"
                        "  P1 --> C3[Run QA validation]:::cmd\n"
                        "  C3 --> E3((QA evidence attached)):::evt\n"
                        "  E3 --> C4[Approve and release]:::cmd\n"
                        "  C4 --> E4((Release completed)):::evt\n"
                        "```\n\n"
                        "## Structured payload example\n\n"
                        "```json\n"
                        "{\n"
                        "  \"feature\": \"onboarding-demo\",\n"
                        "  \"priority\": \"high\",\n"
                        "  \"owner\": \"product\",\n"
                        "  \"acceptance\": [\n"
                        "    \"Flow diagram renders\",\n"
                        "    \"Task evidence visible\",\n"
                        "    \"Checks panel is understandable\"\n"
                        "  ]\n"
                        "}\n"
                        "```\n"
                    ),
                    "status": "Ready",
                    "tags": ["demo", "onboarding", "architecture"],
                    "external_refs": [
                        {"url": "https://mermaid.js.org/", "title": "Mermaid documentation"},
                        {"url": "https://docs.github.com/en/repositories", "title": "Repository docs"},
                    ],
                    "attachment_refs": [],
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                },
                expected_version=0,
            )

        if current_version(db, "Note", BOOTSTRAP_NOTE_DEMO_ID) == 0:
            append_event(
                db,
                aggregate_type="Note",
                aggregate_id=BOOTSTRAP_NOTE_DEMO_ID,
                event_type=NOTE_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_group_id": BOOTSTRAP_NOTE_DISCOVERY_GROUP_ID,
                    "task_id": None,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                    "title": "Welcome: What to try first",
                    "body": (
                        "## Quick checklist\n\n"
                        "- Open **Tasks** and switch list/board views.\n"
                        "- Open **Specifications** and view Mermaid + JSON blocks.\n"
                        "- Open **Project > Delivery Checks** and inspect required checks.\n"
                        "- Use **Chat** to create a new project in one sentence.\n\n"
                        "## Tip\n\n"
                        "Use fenced code blocks for logs, payloads, and API snippets."
                    ),
                    "tags": ["welcome", "demo", "checklist"],
                    "external_refs": [
                        {"url": "https://github.com/nirm3l/constructos/blob/main/README.md", "title": "Quick start README"},
                    ],
                    "attachment_refs": [],
                    "pinned": True,
                    "archived": False,
                    "created_at": to_iso_utc(datetime.now(timezone.utc)),
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_id": BOOTSTRAP_NOTE_DEMO_ID,
                },
                expected_version=0,
            )
        if current_version(db, "Note", BOOTSTRAP_NOTE_EXECUTION_ID) == 0:
            append_event(
                db,
                aggregate_type="Note",
                aggregate_id=BOOTSTRAP_NOTE_EXECUTION_ID,
                event_type=NOTE_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_group_id": BOOTSTRAP_NOTE_DISCOVERY_GROUP_ID,
                    "task_id": BOOTSTRAP_TASK_AUTOMATION_TOUR_ID,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                    "title": "Execution notes: demo implementation journal",
                    "body": (
                        "## Goal\n\n"
                        "Capture implementation context while working so handoffs stay explicit.\n\n"
                        "## Example timeline\n\n"
                        "1. Parsed the specification and extracted acceptance criteria.\n"
                        "2. Implemented baseline task flow and verified board transitions.\n"
                        "3. Ran automation once and captured the output signal.\n"
                        "4. Documented open risks and concrete next actions.\n\n"
                        "## What good notes include\n\n"
                        "- Decision made and why.\n"
                        "- Scope that was changed and scope that was intentionally skipped.\n"
                        "- Evidence pointers (task comments, commit IDs, screenshots, logs).\n"
                        "- Next owner and expected status move.\n\n"
                        "## Risks template\n\n"
                        "- **Risk:** unclear dependency ownership.\n"
                        "- **Impact:** delivery delay.\n"
                        "- **Mitigation:** assign owner and add visible blocker comment on task."
                    ),
                    "tags": ["demo", "execution", "handoff"],
                    "external_refs": [
                        {"url": "https://docs.github.com/en/issues/tracking-your-work-with-issues/about-task-lists", "title": "Task tracking guide"},
                    ],
                    "attachment_refs": [],
                    "pinned": False,
                    "archived": False,
                    "created_at": to_iso_utc(datetime.now(timezone.utc)),
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_id": BOOTSTRAP_NOTE_EXECUTION_ID,
                },
                expected_version=0,
            )
        if current_version(db, "Note", BOOTSTRAP_NOTE_RELEASE_ID) == 0:
            append_event(
                db,
                aggregate_type="Note",
                aggregate_id=BOOTSTRAP_NOTE_RELEASE_ID,
                event_type=NOTE_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_group_id": BOOTSTRAP_NOTE_SHIP_GROUP_ID,
                    "task_id": None,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                    "title": "Release readiness: checklist and evidence model",
                    "body": (
                        "## Release intent\n\n"
                        "This note shows how a team can document release readiness in one place.\n\n"
                        "## Readiness checklist\n\n"
                        "- Scope frozen and linked to specification acceptance criteria.\n"
                        "- Required delivery checks reviewed.\n"
                        "- QA execution evidence attached and traceable.\n"
                        "- Rollback path documented.\n"
                        "- Post-release observation owner assigned.\n\n"
                        "## Evidence contract (example)\n\n"
                        "```json\n"
                        "{\n"
                        "  \"release_id\": \"demo-r1\",\n"
                        "  \"checks\": [\"build\", \"qa\", \"deploy\"],\n"
                        "  \"artifacts\": {\n"
                        "    \"qa_report\": \"attached\",\n"
                        "    \"deploy_log\": \"attached\",\n"
                        "    \"rollback_plan\": \"documented\"\n"
                        "  },\n"
                        "  \"approved_by\": \"lead\"\n"
                        "}\n"
                        "```\n\n"
                        "## Post-release notes\n\n"
                        "Use this section for incident-free confirmation, observed regressions, and follow-up tasks."
                    ),
                    "tags": ["demo", "release", "evidence"],
                    "external_refs": [
                        {"url": "https://12factor.net/", "title": "The Twelve-Factor App"},
                    ],
                    "attachment_refs": [],
                    "pinned": False,
                    "archived": False,
                    "created_at": to_iso_utc(datetime.now(timezone.utc)),
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "note_id": BOOTSTRAP_NOTE_RELEASE_ID,
                },
                expected_version=0,
            )

        if current_version(db, "Task", BOOTSTRAP_TASK_ID) == 0:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=BOOTSTRAP_TASK_ID,
                event_type=TASK_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_group_id": BOOTSTRAP_TASK_SPRINT_A_ID,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                    "title": "Setup your first task",
                    "description": "Use FAB + to add tasks quickly, then open board view and move this item across statuses.",
                    "status": "To do",
                    "priority": "Med",
                    "due_date": to_iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
                    "assignee_id": DEFAULT_USER_ID,
                    "assigned_agent_code": None,
                    "labels": ["welcome", "demo", "board"],
                    "subtasks": [],
                    "attachments": [],
                    "external_refs": [],
                    "attachment_refs": [],
                    "recurring_rule": None,
                    "order_index": 1,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_id": BOOTSTRAP_TASK_ID,
                },
                expected_version=0,
            )

        if current_version(db, "Task", BOOTSTRAP_TASK_BOARD_TOUR_ID) == 0:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=BOOTSTRAP_TASK_BOARD_TOUR_ID,
                event_type=TASK_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_group_id": BOOTSTRAP_TASK_SPRINT_A_ID,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                    "title": "Board demo: move this card to Dev",
                    "description": "Use drag-and-drop to validate board status transitions and ordering.",
                    "status": "To do",
                    "priority": "Low",
                    "due_date": None,
                    "assignee_id": DEFAULT_USER_ID,
                    "assigned_agent_code": None,
                    "labels": ["demo", "board", "kanban"],
                    "subtasks": [],
                    "attachments": [],
                    "external_refs": [],
                    "attachment_refs": [],
                    "recurring_rule": None,
                    "order_index": 2,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_id": BOOTSTRAP_TASK_BOARD_TOUR_ID,
                },
                expected_version=0,
            )

        if current_version(db, "Task", BOOTSTRAP_TASK_AUTOMATION_TOUR_ID) == 0:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=BOOTSTRAP_TASK_AUTOMATION_TOUR_ID,
                event_type=TASK_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_group_id": BOOTSTRAP_TASK_SPRINT_B_ID,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                    "title": "Automation demo: run with an agent",
                    "description": "Open this task and use Run now to see live automation output and execution state.",
                    "status": "In progress",
                    "priority": "Med",
                    "due_date": None,
                    "assignee_id": DEFAULT_USER_ID,
                    "assigned_agent_code": None,
                    "labels": ["demo", "automation", "agent"],
                    "subtasks": [],
                    "attachments": [],
                    "external_refs": [
                        {"url": "https://platform.openai.com/docs", "title": "OpenAI API docs"},
                    ],
                    "attachment_refs": [],
                    "recurring_rule": None,
                    "order_index": 3,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_id": BOOTSTRAP_TASK_AUTOMATION_TOUR_ID,
                },
                expected_version=0,
            )

        if current_version(db, "Task", BOOTSTRAP_TASK_KNOWLEDGE_TOUR_ID) == 0:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=BOOTSTRAP_TASK_KNOWLEDGE_TOUR_ID,
                event_type=TASK_EVENT_CREATED,
                payload={
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_group_id": BOOTSTRAP_TASK_SPRINT_B_ID,
                    "specification_id": BOOTSTRAP_SPEC_DEMO_ID,
                    "title": "Knowledge demo: inspect context snapshot",
                    "description": "Open Project > Context and review graph context and prompt segment breakdown.",
                    "status": "Done",
                    "priority": "Low",
                    "due_date": None,
                    "assignee_id": DEFAULT_USER_ID,
                    "assigned_agent_code": None,
                    "labels": ["demo", "knowledge-graph", "context"],
                    "subtasks": [],
                    "attachments": [],
                    "external_refs": [],
                    "attachment_refs": [],
                    "recurring_rule": None,
                    "order_index": 4,
                },
                metadata={
                    "actor_id": DEFAULT_USER_ID,
                    "workspace_id": BOOTSTRAP_WORKSPACE_ID,
                    "project_id": BOOTSTRAP_PROJECT_ID,
                    "task_id": BOOTSTRAP_TASK_KNOWLEDGE_TOUR_ID,
                },
                expected_version=0,
            )

        # Keep bootstrap demo tasks aligned with Demo board statuses.
        automation_demo_task = db.get(Task, BOOTSTRAP_TASK_AUTOMATION_TOUR_ID)
        if automation_demo_task is not None and (automation_demo_task.status or "").strip() == "Dev":
            automation_demo_task.status = "In progress"
        knowledge_demo_task = db.get(Task, BOOTSTRAP_TASK_KNOWLEDGE_TOUR_ID)
        if knowledge_demo_task is not None and (knowledge_demo_task.status or "").strip() == "QA":
            knowledge_demo_task.status = "Done"
        _seed_demo_event_storming_scaffold()
        db.commit()

        # Repair drift: if Kurrent was reset but app.db persisted, backfill streams.
        _backfill_project_streams_from_read_model(db)
        _backfill_task_group_streams_from_read_model(db)
        _backfill_note_group_streams_from_read_model(db)
        _backfill_project_rule_streams_from_read_model(db)
        _backfill_specification_streams_from_read_model(db)
        _backfill_task_streams_from_read_model(db)
        _rebuild_project_tag_index(db)
        _backfill_project_members_for_existing_projects(db)
        _repair_vector_index_drift(db)
        db.commit()


def startup_bootstrap():
    active_database_url = shared_models.ensure_engine()
    if active_database_url.startswith("sqlite"):
        db_path = active_database_url.removeprefix("sqlite:///")
        if db_path:
            os.makedirs(Path(db_path).parent, exist_ok=True)
    last_exc: Exception | None = None
    for _ in range(20):
        try:
            bootstrap_data()
            last_exc = None
            break
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            time.sleep(1)
    if last_exc is not None:
        raise last_exc


def bootstrap_payload(db: Session, user: User) -> dict[str, Any]:
    return bootstrap_payload_read_model(db, user)


def _backfill_project_streams_from_read_model(db: Session) -> None:
    """
    If EventStore/Kurrent was reset but app.db is persisted, we can end up with
    read-model rows that have no corresponding event streams. That breaks edits
    (commands rely on rebuild_state when Kurrent is enabled).
    """
    if get_kurrent_client() is None:
        return

    projects = db.execute(select(Project).where(Project.is_deleted == False)).scalars().all()
    for p in projects:
        if current_version(db, "Project", p.id) != 0:
            continue
        try:
            custom_statuses = json.loads(p.custom_statuses or "[]")
        except Exception:
            custom_statuses = DEFAULT_STATUSES
        try:
            external_refs = json.loads(p.external_refs or "[]")
        except Exception:
            external_refs = []
        try:
            attachment_refs = json.loads(p.attachment_refs or "[]")
        except Exception:
            attachment_refs = []

        append_event(
            db,
            aggregate_type="Project",
            aggregate_id=p.id,
            event_type=PROJECT_EVENT_CREATED,
            payload={
                "workspace_id": p.workspace_id,
                "name": p.name,
                "description": p.description or "",
                "custom_statuses": custom_statuses or DEFAULT_STATUSES,
                "external_refs": external_refs,
                "attachment_refs": attachment_refs,
                "chat_index_mode": str(getattr(p, "chat_index_mode", "") or "OFF"),
                "chat_attachment_ingestion_mode": str(
                    getattr(p, "chat_attachment_ingestion_mode", "") or "METADATA_ONLY"
                ),
                "event_storming_enabled": bool(getattr(p, "event_storming_enabled", True)),
            },
            metadata={"actor_id": DEFAULT_USER_ID, "workspace_id": p.workspace_id, "project_id": p.id},
            expected_version=0,
        )


def _backfill_task_group_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    groups = db.execute(select(TaskGroup).where(TaskGroup.is_deleted == False)).scalars().all()
    for group in groups:
        if current_version(db, "TaskGroup", group.id) != 0:
            continue
        append_event(
            db,
            aggregate_type="TaskGroup",
            aggregate_id=group.id,
            event_type=TASK_GROUP_EVENT_CREATED,
            payload={
                "workspace_id": group.workspace_id,
                "project_id": group.project_id,
                "name": group.name,
                "description": group.description or "",
                "color": group.color,
                "order_index": int(group.order_index or 0),
                "is_deleted": bool(group.is_deleted),
            },
            metadata={
                "actor_id": DEFAULT_USER_ID,
                "workspace_id": group.workspace_id,
                "project_id": group.project_id,
                "task_group_id": group.id,
            },
            expected_version=0,
        )


def _backfill_note_group_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    groups = db.execute(select(NoteGroup).where(NoteGroup.is_deleted == False)).scalars().all()
    for group in groups:
        if current_version(db, "NoteGroup", group.id) != 0:
            continue
        append_event(
            db,
            aggregate_type="NoteGroup",
            aggregate_id=group.id,
            event_type=NOTE_GROUP_EVENT_CREATED,
            payload={
                "workspace_id": group.workspace_id,
                "project_id": group.project_id,
                "name": group.name,
                "description": group.description or "",
                "color": group.color,
                "order_index": int(group.order_index or 0),
                "is_deleted": bool(group.is_deleted),
            },
            metadata={
                "actor_id": DEFAULT_USER_ID,
                "workspace_id": group.workspace_id,
                "project_id": group.project_id,
                "note_group_id": group.id,
            },
            expected_version=0,
        )


def _backfill_task_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    tasks = db.execute(select(Task).where(Task.is_deleted == False)).scalars().all()
    for t in tasks:
        if current_version(db, "Task", t.id) != 0:
            continue
        try:
            labels = json.loads(t.labels or "[]")
        except Exception:
            labels = []
        try:
            subtasks = json.loads(t.subtasks or "[]")
        except Exception:
            subtasks = []
        try:
            attachments = json.loads(t.attachments or "[]")
        except Exception:
            attachments = []
        try:
            external_refs = json.loads(t.external_refs or "[]")
        except Exception:
            external_refs = []
        try:
            attachment_refs = json.loads(t.attachment_refs or "[]")
        except Exception:
            attachment_refs = attachments
        try:
            execution_triggers = json.loads(t.execution_triggers or "[]")
        except Exception:
            execution_triggers = []

        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=t.id,
            event_type=TASK_EVENT_CREATED,
            payload={
                "workspace_id": t.workspace_id,
                "project_id": t.project_id,
                "specification_id": t.specification_id,
                "title": t.title,
                "description": t.description or "",
                "status": t.status or "To do",
                "priority": t.priority or "Med",
                "due_date": to_iso_utc(t.due_date),
                "assignee_id": t.assignee_id,
                "labels": labels,
                "subtasks": subtasks,
                "attachments": attachments,
                "external_refs": external_refs,
                "attachment_refs": attachment_refs,
                "instruction": t.instruction,
                "execution_triggers": execution_triggers,
                "recurring_rule": t.recurring_rule,
                "order_index": int(t.order_index or 0),
                "task_type": t.task_type or "manual",
                "scheduled_instruction": t.scheduled_instruction,
                "scheduled_at_utc": to_iso_utc(t.scheduled_at_utc),
                "schedule_timezone": t.schedule_timezone,
                "schedule_state": t.schedule_state or "idle",
            },
            metadata={
                "actor_id": DEFAULT_USER_ID,
                "workspace_id": t.workspace_id,
                "project_id": t.project_id,
                "task_id": t.id,
            },
            expected_version=0,
        )


def _backfill_project_rule_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    rules = db.execute(select(ProjectRule).where(ProjectRule.is_deleted == False)).scalars().all()
    for rule in rules:
        if current_version(db, "ProjectRule", rule.id) != 0:
            continue
        append_event(
            db,
            aggregate_type="ProjectRule",
            aggregate_id=rule.id,
            event_type=PROJECT_RULE_EVENT_CREATED,
            payload={
                "workspace_id": rule.workspace_id,
                "project_id": rule.project_id,
                "title": rule.title,
                "body": rule.body or "",
                "created_by": rule.created_by,
                "updated_by": rule.updated_by,
                "is_deleted": False,
            },
            metadata={
                "actor_id": rule.created_by or DEFAULT_USER_ID,
                "workspace_id": rule.workspace_id,
                "project_id": rule.project_id,
                "project_rule_id": rule.id,
            },
            expected_version=0,
        )


def _backfill_specification_streams_from_read_model(db: Session) -> None:
    if get_kurrent_client() is None:
        return

    specifications = db.execute(select(Specification).where(Specification.is_deleted == False)).scalars().all()
    for specification in specifications:
        if current_version(db, "Specification", specification.id) != 0:
            continue
        try:
            external_refs = json.loads(specification.external_refs or "[]")
        except Exception:
            external_refs = []
        try:
            attachment_refs = json.loads(specification.attachment_refs or "[]")
        except Exception:
            attachment_refs = []
        try:
            tags = json.loads(specification.tags or "[]")
        except Exception:
            tags = []
        append_event(
            db,
            aggregate_type="Specification",
            aggregate_id=specification.id,
            event_type=SPECIFICATION_EVENT_CREATED,
            payload={
                "workspace_id": specification.workspace_id,
                "project_id": specification.project_id,
                "title": specification.title,
                "body": specification.body or "",
                "status": specification.status or "Draft",
                "tags": tags,
                "external_refs": external_refs,
                "attachment_refs": attachment_refs,
                "created_by": specification.created_by,
                "updated_by": specification.updated_by,
                "archived": bool(specification.archived),
                "is_deleted": False,
            },
            metadata={
                "actor_id": specification.created_by or DEFAULT_USER_ID,
                "workspace_id": specification.workspace_id,
                "project_id": specification.project_id,
                "specification_id": specification.id,
            },
            expected_version=0,
        )


def _backfill_project_members_for_existing_projects(db: Session) -> None:
    projects = db.execute(select(Project).where(Project.is_deleted == False)).scalars().all()
    for project in projects:
        has_members = db.execute(
            select(func.count(ProjectMember.id)).where(
                ProjectMember.project_id == project.id,
            )
        ).scalar() or 0
        if has_members > 0:
            continue
        # Safe default: assign workspace owners to existing projects.
        owners = db.execute(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == project.workspace_id,
                WorkspaceMember.role.in_(["Owner", "Admin"]),
            )
        ).scalars().all()
        if not owners:
            owners = [DEFAULT_USER_ID]
        for uid in dict.fromkeys(owners):
            db.add(
                ProjectMember(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    user_id=uid,
                    role="Owner",
                )
            )


def _repair_vector_index_drift(db: Session) -> None:
    try:
        from .vector_store import maybe_reindex_project, project_embedding_index_snapshot, vector_store_enabled
    except Exception as exc:  # pragma: no cover
        logger.warning("Vector drift repair unavailable: %s", exc)
        return

    if not vector_store_enabled():
        return

    projects = db.execute(
        select(Project).where(
            Project.is_deleted == False,
            Project.embedding_enabled == True,
        )
    ).scalars().all()
    for project in projects:
        snapshot = project_embedding_index_snapshot(
            db,
            project_id=project.id,
            embedding_enabled=bool(project.embedding_enabled),
            embedding_model=project.embedding_model,
            chat_index_mode=str(getattr(project, "chat_index_mode", "") or "OFF"),
            chat_attachment_ingestion_mode=str(
                getattr(project, "chat_attachment_ingestion_mode", "") or "METADATA_ONLY"
            ),
        )
        status = str(snapshot.get("status") or "").strip().lower()
        expected_entities = int(snapshot.get("expected_entities") or 0)
        indexed_entities = int(snapshot.get("indexed_entities") or 0)
        gap = max(0, expected_entities - indexed_entities)
        if status != "indexing" or gap <= 0:
            continue
        logger.info(
            "Vector drift repair: project_id=%s indexed=%s expected=%s gap=%s",
            project.id,
            indexed_entities,
            expected_entities,
            gap,
        )
        try:
            maybe_reindex_project(
                db,
                project_id=project.id,
                embedding_enabled=bool(project.embedding_enabled),
                embedding_model=project.embedding_model,
                chat_index_mode=str(getattr(project, "chat_index_mode", "") or "OFF"),
                chat_attachment_ingestion_mode=str(
                    getattr(project, "chat_attachment_ingestion_mode", "") or "METADATA_ONLY"
                ),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Vector drift repair failed for project_id=%s: %s", project.id, exc)


def _parse_tag_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        tag = str(value or "").strip().lower()
        if tag:
            out.append(tag)
    return out


def _rebuild_project_tag_index(db: Session) -> None:
    db.query(ProjectTagIndex).delete()
    projects = db.execute(select(Project).where(Project.is_deleted == False)).scalars().all()
    for project in projects:
        counts: dict[str, int] = {}
        task_rows = db.execute(
            select(Task.labels).where(
                Task.project_id == project.id,
                Task.is_deleted == False,
                Task.archived == False,
            )
        ).all()
        note_rows = db.execute(
            select(Note.tags).where(
                Note.project_id == project.id,
                Note.is_deleted == False,
                Note.archived == False,
            )
        ).all()
        specification_rows = db.execute(
            select(Specification.tags).where(
                Specification.project_id == project.id,
                Specification.is_deleted == False,
                Specification.archived == False,
            )
        ).all()
        for (labels_raw,) in task_rows:
            for tag in _parse_tag_list(labels_raw):
                counts[tag] = counts.get(tag, 0) + 1
        for (tags_raw,) in note_rows:
            for tag in _parse_tag_list(tags_raw):
                counts[tag] = counts.get(tag, 0) + 1
        for (tags_raw,) in specification_rows:
            for tag in _parse_tag_list(tags_raw):
                counts[tag] = counts.get(tag, 0) + 1
        for tag, usage_count in sorted(counts.items(), key=lambda item: item[0]):
            db.add(
                ProjectTagIndex(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    tag=tag,
                    usage_count=usage_count,
                )
            )
