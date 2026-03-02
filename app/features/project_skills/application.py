from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from features.rules.application import ProjectRuleApplicationService
from features.agents.gates import DEFAULT_GATE_POLICY as _DEFAULT_AGENT_GATE_POLICY
from shared.core import Project, ProjectRuleCreate, ProjectRulePatch, User, ensure_project_access, ensure_role
from shared.models import ProjectMember, ProjectRule, ProjectSkill, User as UserModel, WorkspaceMember, WorkspaceSkill

from .read_models import load_project_skill_view, load_workspace_skill_view

_ALLOWED_MODES = {"advisory", "enforced"}
_ALLOWED_TRUST_LEVELS = {"verified", "reviewed", "untrusted"}
_MAX_SOURCE_BYTES = 1024 * 1024
_KEY_SANITIZER_RE = re.compile(r"[^a-z0-9]+")
_FILE_NAME_SANITIZER_RE = re.compile(r"[^A-Za-z0-9._-]+")
_FRONTMATTER_FIELD_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
_TEAM_MODE_SKILL_KEY = "team_mode"
_GIT_DELIVERY_SKILL_KEY = "git_delivery"
_GITHUB_DELIVERY_SKILL_KEY = "github_delivery"
_GATE_POLICY_RULE_TITLE = "Gate Policy"
_GATE_POLICY_RULE_TITLES = ("gate policy", "delivery gates", "workflow gates")
_GATE_POLICY_RELEVANT_SKILL_KEYS = {
    _TEAM_MODE_SKILL_KEY,
    _GIT_DELIVERY_SKILL_KEY,
    _GITHUB_DELIVERY_SKILL_KEY,
}
_DEFAULT_GATE_POLICY: dict[str, Any] = deepcopy(_DEFAULT_AGENT_GATE_POLICY)
_SKILL_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    _GITHUB_DELIVERY_SKILL_KEY: (_GIT_DELIVERY_SKILL_KEY,),
    _TEAM_MODE_SKILL_KEY: (_GIT_DELIVERY_SKILL_KEY,),
}
_TEAM_MODE_WORKSPACE_ROLE = "Admin"
_TEAM_MODE_AGENT_SPECS: tuple[dict[str, str], ...] = (
    {
        "username": "agent.m0rph3u5",
        "full_name": "M0rph3u5",
        "project_role": "TeamLeadAgent",
    },
    {
        "username": "agent.tr1n1ty",
        "full_name": "Tr1n1ty",
        "project_role": "DeveloperAgent",
    },
    {
        "username": "agent.n30",
        "full_name": "N30",
        "project_role": "DeveloperAgent",
    },
    {
        "username": "agent.0r4cl3",
        "full_name": "0r4cl3",
        "project_role": "QAAgent",
    },
)


def _normalize_mode(raw: str) -> str:
    value = str(raw or "advisory").strip().lower()
    if value not in _ALLOWED_MODES:
        allowed = ", ".join(sorted(_ALLOWED_MODES))
        raise HTTPException(status_code=422, detail=f"mode must be one of: {allowed}")
    return value


def _normalize_trust_level(raw: str) -> str:
    value = str(raw or "reviewed").strip().lower()
    if value not in _ALLOWED_TRUST_LEVELS:
        allowed = ", ".join(sorted(_ALLOWED_TRUST_LEVELS))
        raise HTTPException(status_code=422, detail=f"trust_level must be one of: {allowed}")
    return value


def _normalize_skill_key(raw: str, *, max_length: int = 128) -> str:
    candidate = str(raw or "").strip().lower()
    candidate = _KEY_SANITIZER_RE.sub("_", candidate).strip("_")
    candidate = candidate[:max_length].strip("_")
    if not candidate:
        raise HTTPException(status_code=422, detail="skill_key cannot be empty")
    return candidate


def _sanitize_source_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="source_url is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail="source_url must use http or https")
    if not parsed.netloc:
        raise HTTPException(status_code=422, detail="source_url must include a valid host")
    return _normalize_source_url(value)


def _normalize_source_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    host = str(parsed.netloc or "").strip().lower()
    path = str(parsed.path or "")
    if host in {"github.com", "www.github.com"}:
        segments = [segment for segment in path.split("/") if segment]
        # Normalize GitHub blob URLs to raw URLs so imports fetch actual markdown/text.
        if len(segments) >= 5 and segments[2] == "blob":
            owner = segments[0]
            repo = segments[1]
            ref = segments[3]
            file_path = "/".join(segments[4:])
            if owner and repo and ref and file_path:
                return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{file_path}"
    if host in {"gist.github.com", "www.gist.github.com"}:
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) >= 2:
            user = segments[0]
            gist_id = segments[1]
            if user and gist_id:
                return f"https://gist.githubusercontent.com/{user}/{gist_id}/raw"
    return source_url


def _default_skill_key_from_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    host = str(parsed.netloc or "").strip().lower()
    path = str(parsed.path or "").strip()
    tail = path.rsplit("/", 1)[-1].strip() if path else ""
    tail = tail.rsplit(".", 1)[0].strip()
    base = tail or host or "imported_skill"
    return _normalize_skill_key(base)


def _sanitize_uploaded_filename(raw: str) -> str:
    candidate = str(raw or "").strip().replace("\\", "/")
    candidate = candidate.rsplit("/", 1)[-1].strip()
    if not candidate:
        candidate = "imported_skill.md"
    normalized = _FILE_NAME_SANITIZER_RE.sub("_", candidate).strip("._")
    normalized = normalized[:160].strip()
    if not normalized:
        normalized = "imported_skill.md"
    return normalized


def _extract_markdown_heading(text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading[:160]
    return ""


def _extract_summary(text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in {"---", "..."}:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("```"):
            continue
        return stripped[:400]
    return ""


def _normalize_frontmatter_value(value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    return normalized


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    raw_text = str(text or "")
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw_text

    end_index = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index < 0:
        return {}, raw_text

    metadata: dict[str, str] = {}
    current_block_key = ""
    current_block_lines: list[str] = []
    for raw_line in lines[1:end_index]:
        stripped = raw_line.strip()

        if current_block_key:
            if raw_line.startswith((" ", "\t")):
                current_block_lines.append(stripped)
                continue
            metadata[current_block_key] = "\n".join(part for part in current_block_lines if part).strip()
            current_block_key = ""
            current_block_lines = []

        if not stripped or stripped.startswith("#"):
            continue
        match = _FRONTMATTER_FIELD_RE.match(stripped)
        if not match:
            continue

        key = str(match.group(1) or "").strip().lower()
        value = _normalize_frontmatter_value(match.group(2))
        if not key:
            continue
        if value in {"|", ">", "|-", ">-"}:
            current_block_key = key
            current_block_lines = []
            continue
        metadata[key] = value

    if current_block_key:
        metadata[current_block_key] = "\n".join(part for part in current_block_lines if part).strip()

    content = "\n".join(lines[end_index + 1:]).lstrip()
    return metadata, content


def _coerce_json_skill_content(payload: dict[str, Any]) -> str:
    for key in ("content", "instructions", "body", "prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    rules = payload.get("rules")
    if isinstance(rules, list):
        lines = [str(item).strip() for item in rules if str(item or "").strip()]
        if lines:
            return "\n".join(f"- {line}" for line in lines)
    steps = payload.get("steps")
    if isinstance(steps, list):
        lines = [str(item).strip() for item in steps if str(item or "").strip()]
        if lines:
            return "\n".join(f"- {line}" for line in lines)
    return ""


def _extract_skill_document(
    *,
    raw_bytes: bytes,
    content_type: str,
    base_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(raw_bytes) > _MAX_SOURCE_BYTES:
        raise HTTPException(status_code=422, detail="Skill source payload is too large")

    content_type_normalized = str(content_type or "").strip().lower()
    manifest: dict[str, Any] = {"content_type": content_type_normalized, **(base_manifest or {})}
    detected_name = ""
    detected_summary = ""
    content_text = ""
    source_version = ""

    decoded_text = raw_bytes.decode("utf-8", errors="replace")
    frontmatter, content_without_frontmatter = _parse_frontmatter(decoded_text)
    frontmatter_name = str(frontmatter.get("title") or frontmatter.get("name") or "").strip()[:160]
    frontmatter_summary = str(frontmatter.get("summary") or frontmatter.get("description") or "").strip()[:400]
    frontmatter_source_version = str(frontmatter.get("version") or frontmatter.get("skill_version") or "").strip()[:64]
    if frontmatter:
        manifest["frontmatter_keys"] = sorted(str(key) for key in frontmatter.keys())[:200]
    should_try_json = "json" in content_type_normalized or decoded_text.lstrip().startswith("{")
    if should_try_json:
        payload: Any = None
        try:
            payload = json.loads(decoded_text)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            detected_name = str(payload.get("name") or payload.get("title") or "").strip()[:160]
            detected_summary = str(payload.get("summary") or payload.get("description") or "").strip()[:400]
            source_version = str(payload.get("version") or payload.get("skill_version") or "").strip()[:64]
            content_text = _coerce_json_skill_content(payload)
            manifest["json_keys"] = sorted(str(key) for key in payload.keys())[:200]

    if not content_text:
        content_text = content_without_frontmatter.strip()

    if not content_text:
        raise HTTPException(status_code=422, detail="Imported skill source is empty")
    content_text = content_text.strip()
    if not content_text:
        raise HTTPException(status_code=422, detail="Imported skill content is empty after normalization")

    if not detected_name:
        detected_name = _extract_markdown_heading(content_text)
    if not detected_name:
        detected_name = frontmatter_name
    if not detected_summary:
        detected_summary = frontmatter_summary
    if not detected_summary:
        detected_summary = _extract_summary(content_text)
    if not source_version:
        source_version = frontmatter_source_version

    return {
        "content": content_text,
        "name": detected_name,
        "summary": detected_summary,
        "source_version": source_version or None,
        "manifest": manifest,
    }


def _fetch_skill_document(source_url: str) -> dict[str, Any]:
    try:
        response = httpx.get(
            source_url,
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "m4tr1x-skill-import/1.0"},
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Skill source fetch failed: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=422, detail=f"Skill source fetch failed with status {response.status_code}")
    return _extract_skill_document(
        raw_bytes=response.content or b"",
        content_type=str(response.headers.get("content-type") or ""),
        base_manifest={"source_status": int(response.status_code)},
    )


def _build_rule_body(
    *,
    skill_key: str,
    source_locator: str,
    trust_level: str,
    mode: str,
    source_version: str | None,
    content: str,
) -> str:
    lines = [
        "Imported skill context:",
        f"- Skill key: `{skill_key}`",
        f"- Source: {source_locator}",
        f"- Trust level: {trust_level}",
        f"- Mode: {mode}",
    ]
    if source_version:
        lines.append(f"- Source version: {source_version}")
    lines.extend(["", "Skill content:", content.strip()])
    return "\n".join(lines).strip()


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or bool(project.is_deleted):
        raise HTTPException(status_code=404, detail="Project not found")
    if str(project.workspace_id) != str(workspace_id):
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def _parse_manifest_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _get_manifest_source_content(manifest_json: str) -> str:
    manifest = _parse_manifest_json(manifest_json)
    return str(manifest.get("source_content") or "").strip()


def _update_manifest_source_content(
    *,
    manifest_json: str,
    source_content: str,
    actor_user_id: str,
) -> str:
    normalized_content = str(source_content or "").strip()
    if not normalized_content:
        raise HTTPException(status_code=422, detail="content cannot be empty")

    manifest = _parse_manifest_json(manifest_json)
    manifest["source_content"] = normalized_content
    manifest["source_content_sha256"] = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["updated_by"] = actor_user_id
    return json.dumps(manifest, ensure_ascii=True, sort_keys=True)


class ProjectSkillApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id

    def _build_project_rule_payload_for_skill(self, *, skill: ProjectSkill, source_content: str) -> tuple[str, str]:
        source_version = str(skill.source_version or "").strip() or None
        title = f"Skill: {skill.name}"
        body = _build_rule_body(
            skill_key=skill.skill_key,
            source_locator=skill.source_locator,
            trust_level=skill.trust_level,
            mode=skill.mode,
            source_version=source_version,
            content=source_content,
        )
        return title, body

    def _derive_command_id(self, suffix: str) -> str | None:
        base = str(self.command_id or "").strip()
        if not base:
            return None
        normalized_suffix = _normalize_skill_key(str(suffix or "").strip() or "op", max_length=40)
        derived = f"{base}:{normalized_suffix}"
        return derived[:64]

    def _find_gate_policy_rule_id(self, *, workspace_id: str, project_id: str) -> str | None:
        rules = self.db.execute(
            select(ProjectRule).where(
                ProjectRule.workspace_id == workspace_id,
                ProjectRule.project_id == project_id,
                ProjectRule.is_deleted == False,  # noqa: E712
            )
        ).scalars()
        for rule in rules:
            title = str(getattr(rule, "title", "") or "").strip().lower()
            if any(marker in title for marker in _GATE_POLICY_RULE_TITLES):
                return str(rule.id)
        return None

    def _ensure_gate_policy_rule_if_needed(
        self,
        *,
        skill: ProjectSkill,
        dependencies: list[dict[str, Any]],
    ) -> str | None:
        relevant_skill_keys = {str(skill.skill_key or "").strip().lower()}
        relevant_skill_keys.update(str(item.get("skill_key") or "").strip().lower() for item in (dependencies or []))
        if not relevant_skill_keys.intersection(_GATE_POLICY_RELEVANT_SKILL_KEYS):
            return None
        existing_rule_id = self._find_gate_policy_rule_id(workspace_id=skill.workspace_id, project_id=skill.project_id)
        if existing_rule_id:
            return existing_rule_id
        rule_command_id = self._derive_command_id("gate-policy") or f"project-gate-policy-{uuid4().hex[:12]}"
        created_rule = ProjectRuleApplicationService(self.db, self.user, command_id=rule_command_id).create_project_rule(
            ProjectRuleCreate(
                workspace_id=skill.workspace_id,
                project_id=skill.project_id,
                title=_GATE_POLICY_RULE_TITLE,
                body=json.dumps(_DEFAULT_GATE_POLICY, ensure_ascii=True),
            )
        )
        created_rule_id = str(created_rule.get("id") or "").strip()
        if not created_rule_id:
            raise HTTPException(status_code=500, detail="Gate policy rule creation failed")
        return created_rule_id

    def _get_workspace_skill_by_key(self, *, workspace_id: str, skill_key: str) -> WorkspaceSkill | None:
        normalized_key = str(skill_key or "").strip().lower()
        if not normalized_key:
            return None
        return self.db.execute(
            select(WorkspaceSkill).where(
                WorkspaceSkill.workspace_id == workspace_id,
                WorkspaceSkill.skill_key == normalized_key,
                WorkspaceSkill.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()

    def _get_project_skill_by_key(self, *, workspace_id: str, project_id: str, skill_key: str) -> ProjectSkill | None:
        normalized_key = str(skill_key or "").strip().lower()
        if not normalized_key:
            return None
        return self.db.execute(
            select(ProjectSkill).where(
                ProjectSkill.workspace_id == workspace_id,
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_key == normalized_key,
                ProjectSkill.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()

    def _attach_workspace_catalog_skill_to_project(
        self,
        *,
        catalog_skill: WorkspaceSkill,
        workspace_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        source_content = _get_manifest_source_content(catalog_skill.manifest_json)
        if not source_content:
            raise HTTPException(status_code=422, detail="Workspace skill source content is missing")

        created = self._import_skill_document(
            workspace_id=workspace_id,
            project_id=project_id,
            requested_source=f"workspace-skill://{catalog_skill.id}",
            source_locator=catalog_skill.source_locator,
            source_type="workspace_catalog",
            fetched={
                "name": catalog_skill.name,
                "summary": catalog_skill.summary,
                "content": source_content,
                "source_version": catalog_skill.source_version,
                "manifest": {
                    "workspace_skill_id": catalog_skill.id,
                    "workspace_skill_key": catalog_skill.skill_key,
                },
            },
            name=catalog_skill.name,
            skill_key=catalog_skill.skill_key,
            mode=catalog_skill.mode,
            trust_level=catalog_skill.trust_level,
        )
        created["attached_from_workspace_skill_id"] = catalog_skill.id
        return created

    def _resolve_skill_dependencies(self, *, skill_key: str) -> list[str]:
        root_key = str(skill_key or "").strip().lower()
        if not root_key:
            return []
        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def _visit(node: str) -> None:
            normalized = str(node or "").strip().lower()
            if not normalized:
                return
            if normalized in visited:
                return
            if normalized in visiting:
                raise HTTPException(status_code=500, detail=f"Skill dependency cycle detected at: {normalized}")
            visiting.add(normalized)
            for dependency in _SKILL_DEPENDENCIES.get(normalized, ()):
                dep_key = str(dependency or "").strip().lower()
                if not dep_key:
                    continue
                _visit(dep_key)
                if dep_key not in ordered:
                    ordered.append(dep_key)
            visiting.remove(normalized)
            visited.add(normalized)

        _visit(root_key)
        return [item for item in ordered if item != root_key]

    def _ensure_skill_dependencies(
        self,
        *,
        workspace_id: str,
        project_id: str,
        root_skill_key: str,
        auto_apply: bool,
    ) -> list[dict[str, Any]]:
        dependency_keys = self._resolve_skill_dependencies(skill_key=root_skill_key)
        if not dependency_keys:
            return []
        resolved: list[dict[str, Any]] = []
        for dependency_key in dependency_keys:
            catalog_skill = self._get_workspace_skill_by_key(
                workspace_id=workspace_id,
                skill_key=dependency_key,
            )
            if catalog_skill is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{root_skill_key} requires workspace {dependency_key} skill",
                )
            attached = False
            applied = False
            dependency_project_skill = self._get_project_skill_by_key(
                workspace_id=workspace_id,
                project_id=project_id,
                skill_key=dependency_key,
            )
            if dependency_project_skill is None:
                attached_view = self._attach_workspace_catalog_skill_to_project(
                    catalog_skill=catalog_skill,
                    workspace_id=workspace_id,
                    project_id=project_id,
                )
                attached = True
                attached_skill_id = str(attached_view.get("id") or "").strip()
                dependency_project_skill = self.db.get(ProjectSkill, attached_skill_id) if attached_skill_id else None
            if dependency_project_skill is None:
                raise HTTPException(status_code=500, detail=f"Failed to ensure dependency skill: {dependency_key}")
            if auto_apply:
                dependency_service = ProjectSkillApplicationService(
                    self.db,
                    self.user,
                    command_id=self._derive_command_id(f"apply-{dependency_key}"),
                )
                dependency_service.apply_project_skill(str(dependency_project_skill.id))
                applied = True
            resolved.append(
                {
                    "skill_key": dependency_key,
                    "project_skill_id": str(dependency_project_skill.id),
                    "attached": attached,
                    "applied": applied,
                }
            )
        return resolved

    def _sync_project_rule_for_skill(
        self,
        *,
        skill: ProjectSkill,
        source_content: str,
        create_if_missing: bool,
    ) -> str | None:
        normalized_content = str(source_content or "").strip()
        if not normalized_content:
            raise HTTPException(status_code=422, detail="Skill content is empty")

        rule_title, rule_body = self._build_project_rule_payload_for_skill(skill=skill, source_content=normalized_content)
        existing_rule_id = str(skill.generated_rule_id or "").strip()
        if existing_rule_id:
            existing_rule = self.db.get(ProjectRule, existing_rule_id)
            if existing_rule is not None and not bool(existing_rule.is_deleted):
                patch_payload = ProjectRulePatch(title=rule_title, body=rule_body)
                ProjectRuleApplicationService(self.db, self.user, command_id=self.command_id).patch_project_rule(
                    existing_rule_id,
                    patch_payload,
                )
                return existing_rule_id
            skill.generated_rule_id = None
            self.db.flush()

        if not create_if_missing:
            return None

        if self.command_id:
            rule_command_id = self._derive_command_id(f"rule-{skill.skill_key}") or self.command_id
        else:
            # No explicit command id: use a unique nonce to avoid replaying stale command executions.
            rule_command_id = f"project-skill-rule-apply-{uuid4().hex}"
        created_rule = ProjectRuleApplicationService(self.db, self.user, command_id=rule_command_id).create_project_rule(
            ProjectRuleCreate(
                workspace_id=skill.workspace_id,
                project_id=skill.project_id,
                title=rule_title,
                body=rule_body,
            )
        )
        created_rule_id = str(created_rule.get("id") or "").strip() or None
        if not created_rule_id:
            raise HTTPException(status_code=500, detail="Skill rule creation failed")
        return created_rule_id

    def _ensure_team_mode_workspace_agent(
        self,
        *,
        workspace_id: str,
        username: str,
        full_name: str,
    ) -> UserModel:
        normalized_username = str(username or "").strip().lower()
        normalized_full_name = str(full_name or "").strip() or normalized_username
        user_row = self.db.execute(
            select(UserModel).where(func.lower(UserModel.username) == normalized_username)
        ).scalar_one_or_none()
        if user_row is not None:
            if str(user_row.user_type or "").strip().lower() != "agent":
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f'Team Mode requires username "{normalized_username}" to be an agent user. '
                        "Found a non-agent user with the same username."
                    ),
                )
            user_row.full_name = normalized_full_name
            user_row.password_hash = None
            user_row.must_change_password = False
            user_row.password_changed_at = None
            user_row.is_active = True
            user_row.user_type = "agent"
        else:
            user_row = UserModel(
                username=normalized_username,
                full_name=normalized_full_name,
                user_type="agent",
                password_hash=None,
                must_change_password=False,
                password_changed_at=None,
                is_active=True,
                theme="dark",
                timezone="UTC",
                notifications_enabled=True,
                agent_chat_model="",
                agent_chat_reasoning_effort="medium",
            )
            self.db.add(user_row)
            self.db.flush()

        workspace_member = self.db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_row.id,
            )
        ).scalar_one_or_none()
        if workspace_member is None:
            self.db.add(
                WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=user_row.id,
                    role=_TEAM_MODE_WORKSPACE_ROLE,
                )
            )
        elif str(workspace_member.role or "").strip() != _TEAM_MODE_WORKSPACE_ROLE:
            workspace_member.role = _TEAM_MODE_WORKSPACE_ROLE
        return user_row

    def _ensure_team_mode_project_membership(self, *, project: Project) -> None:
        for spec in _TEAM_MODE_AGENT_SPECS:
            user_row = self._ensure_team_mode_workspace_agent(
                workspace_id=project.workspace_id,
                username=spec["username"],
                full_name=spec["full_name"],
            )
            expected_project_role = str(spec["project_role"])
            project_member = self.db.execute(
                select(ProjectMember).where(
                    ProjectMember.workspace_id == project.workspace_id,
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == user_row.id,
                )
            ).scalar_one_or_none()
            if project_member is None:
                self.db.add(
                    ProjectMember(
                        workspace_id=project.workspace_id,
                        project_id=project.id,
                        user_id=user_row.id,
                        role=expected_project_role,
                    )
                )
                continue
            if str(project_member.role or "").strip() != expected_project_role:
                project_member.role = expected_project_role

    def _apply_team_mode_contract_if_needed(self, *, skill: ProjectSkill) -> None:
        if str(skill.skill_key or "").strip().lower() != _TEAM_MODE_SKILL_KEY:
            return
        ensure_role(self.db, skill.workspace_id, self.user.id, {"Owner", "Admin"})
        project = _require_project_scope(
            self.db,
            workspace_id=skill.workspace_id,
            project_id=skill.project_id,
        )
        self._ensure_team_mode_project_membership(project=project)
        self.db.flush()

    def _build_team_mode_roster_snapshot(self, *, project: Project) -> list[dict[str, Any]]:
        roster: list[dict[str, Any]] = []
        for spec in _TEAM_MODE_AGENT_SPECS:
            normalized_username = str(spec["username"]).strip().lower()
            user_row = self.db.execute(
                select(UserModel).where(func.lower(UserModel.username) == normalized_username)
            ).scalar_one_or_none()
            user_id = str(user_row.id) if user_row is not None else ""
            workspace_member = None
            project_member = None
            if user_row is not None:
                workspace_member = self.db.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == project.workspace_id,
                        WorkspaceMember.user_id == user_row.id,
                    )
                ).scalar_one_or_none()
                project_member = self.db.execute(
                    select(ProjectMember).where(
                        ProjectMember.workspace_id == project.workspace_id,
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == user_row.id,
                    )
                ).scalar_one_or_none()
            roster.append(
                {
                    "username": str(spec["username"]),
                    "full_name": str(spec["full_name"]),
                    "expected_project_role": str(spec["project_role"]),
                    "user_id": user_id or None,
                    "user_type": (str(user_row.user_type or "").strip() if user_row is not None else None),
                    "workspace_member_role": (
                        str(workspace_member.role or "").strip() if workspace_member is not None else None
                    ),
                    "project_member_role": (
                        str(project_member.role or "").strip() if project_member is not None else None
                    ),
                    "workspace_member_present": workspace_member is not None,
                    "project_member_present": project_member is not None,
                }
            )
        return roster

    def _assert_generated_rule_id_uniqueness(self, *, skill: ProjectSkill) -> None:
        generated_rule_id = str(skill.generated_rule_id or "").strip()
        if not generated_rule_id:
            return
        collisions = self.db.execute(
            select(ProjectSkill).where(
                ProjectSkill.workspace_id == skill.workspace_id,
                ProjectSkill.project_id == skill.project_id,
                ProjectSkill.generated_rule_id == generated_rule_id,
                ProjectSkill.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()
        conflicting = [row for row in collisions if str(row.id) != str(skill.id) and str(row.skill_key) != str(skill.skill_key)]
        if conflicting:
            conflict_keys = ", ".join(sorted({str(item.skill_key) for item in conflicting}))
            raise HTTPException(
                status_code=500,
                detail=f"generated_rule_id collision for skill {skill.skill_key}: also used by {conflict_keys}",
            )

    def _import_skill_document(
        self,
        *,
        workspace_id: str,
        project_id: str,
        requested_source: str,
        source_locator: str,
        source_type: str,
        fetched: dict[str, Any],
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
    ) -> dict[str, Any]:
        detected_name = str(fetched.get("name") or "").strip()
        detected_summary = str(fetched.get("summary") or "").strip()
        content = str(fetched.get("content") or "").strip()
        source_version = str(fetched.get("source_version") or "").strip() or None
        if not content:
            raise HTTPException(status_code=422, detail="Imported skill content is empty")

        normalized_mode = _normalize_mode(mode)
        normalized_trust = _normalize_trust_level(trust_level)
        effective_name = str(name or "").strip() or detected_name or "Imported Skill"
        effective_summary = detected_summary or f"Imported from {source_locator}"
        key_candidate = str(skill_key or "").strip() or effective_name or _default_skill_key_from_url(source_locator)
        normalized_key = _normalize_skill_key(key_candidate)

        existing = self.db.execute(
            select(ProjectSkill).where(
                ProjectSkill.workspace_id == workspace_id,
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_key == normalized_key,
            )
        ).scalar_one_or_none()
        is_restore = existing is not None and bool(existing.is_deleted)
        is_update_existing = existing is not None and (not bool(existing.is_deleted))

        generated_rule_id: str | None = None
        if existing is not None and (is_restore or is_update_existing):
            existing_rule_id = str(existing.generated_rule_id or "").strip()
            if existing_rule_id:
                existing_rule = self.db.get(ProjectRule, existing_rule_id)
                if existing_rule is not None and not bool(existing_rule.is_deleted):
                    rule_title = f"Skill: {effective_name}"
                    rule_body = _build_rule_body(
                        skill_key=normalized_key,
                        source_locator=source_locator,
                        trust_level=normalized_trust,
                        mode=normalized_mode,
                        source_version=source_version,
                        content=content,
                    )
                    patch_payload = ProjectRulePatch(title=rule_title, body=rule_body)
                    ProjectRuleApplicationService(self.db, self.user, command_id=self.command_id).patch_project_rule(
                        existing_rule_id,
                        patch_payload,
                    )
                    generated_rule_id = existing_rule_id

        imported_at = datetime.now(timezone.utc).isoformat()
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest = {
            "requested_source_url": requested_source,
            "source_url": source_locator,
            "requested_source_locator": requested_source,
            "source_locator": source_locator,
            "source_version": source_version,
            "detected_name": detected_name,
            "detected_summary": detected_summary,
            "source_content": content,
            "source_content_sha256": source_hash,
            "imported_at": imported_at,
            **(fetched.get("manifest") if isinstance(fetched.get("manifest"), dict) else {}),
        }
        if existing is not None and (is_restore or is_update_existing):
            existing.name = effective_name
            existing.summary = effective_summary
            existing.source_type = source_type
            existing.source_locator = source_locator
            existing.source_version = source_version
            existing.trust_level = normalized_trust
            existing.mode = normalized_mode
            existing.generated_rule_id = generated_rule_id
            existing.manifest_json = json.dumps(manifest, ensure_ascii=True, sort_keys=True)
            existing.updated_by = self.user.id
            existing.is_deleted = False
            skill_entity = existing
        else:
            skill_entity = ProjectSkill(
                workspace_id=workspace_id,
                project_id=project_id,
                skill_key=normalized_key,
                name=effective_name,
                summary=effective_summary,
                source_type=source_type,
                source_locator=source_locator,
                source_version=source_version,
                trust_level=normalized_trust,
                mode=normalized_mode,
                generated_rule_id=generated_rule_id,
                manifest_json=json.dumps(manifest, ensure_ascii=True, sort_keys=True),
                created_by=self.user.id,
                updated_by=self.user.id,
                is_deleted=False,
            )
            self.db.add(skill_entity)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if "ux_project_skills_project_key" in str(exc):
                raise HTTPException(status_code=409, detail=f"Skill key already exists in project: {normalized_key}") from exc
            raise
        view = load_project_skill_view(self.db, skill_entity.id)
        if view is None:
            raise HTTPException(status_code=500, detail="Project skill was not created")
        view["already_exists"] = False
        view["updated_existing"] = bool(is_update_existing)
        view["restored_existing"] = bool(is_restore)
        return view

    def import_skill_from_url(
        self,
        *,
        workspace_id: str,
        project_id: str,
        source_url: str,
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
    ) -> dict[str, Any]:
        ensure_role(self.db, workspace_id, self.user.id, {"Owner", "Admin", "Member"})
        ensure_project_access(self.db, workspace_id, project_id, self.user.id, {"Owner", "Admin", "Member"})
        _require_project_scope(self.db, workspace_id=workspace_id, project_id=project_id)

        requested_source = str(source_url or "").strip()
        source_locator = _sanitize_source_url(source_url)
        fetched = _fetch_skill_document(source_locator)
        return self._import_skill_document(
            workspace_id=workspace_id,
            project_id=project_id,
            requested_source=requested_source,
            source_locator=source_locator,
            source_type="url",
            fetched=fetched,
            name=name,
            skill_key=skill_key,
            mode=mode,
            trust_level=trust_level,
        )

    def import_skill_from_file(
        self,
        *,
        workspace_id: str,
        project_id: str,
        file_name: str,
        file_content: bytes,
        file_content_type: str = "",
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
    ) -> dict[str, Any]:
        ensure_role(self.db, workspace_id, self.user.id, {"Owner", "Admin", "Member"})
        ensure_project_access(self.db, workspace_id, project_id, self.user.id, {"Owner", "Admin", "Member"})
        _require_project_scope(self.db, workspace_id=workspace_id, project_id=project_id)

        normalized_file_name = _sanitize_uploaded_filename(file_name)
        if not file_content:
            raise HTTPException(status_code=422, detail="Skill file is empty")
        source_locator = f"upload://{normalized_file_name}"
        fetched = _extract_skill_document(
            raw_bytes=file_content,
            content_type=file_content_type,
            base_manifest={
                "upload_file_name": normalized_file_name,
                "upload_content_type": str(file_content_type or "").strip(),
                "upload_size_bytes": len(file_content),
            },
        )
        return self._import_skill_document(
            workspace_id=workspace_id,
            project_id=project_id,
            requested_source=normalized_file_name,
            source_locator=source_locator,
            source_type="file",
            fetched=fetched,
            name=name,
            skill_key=skill_key,
            mode=mode,
            trust_level=trust_level,
        )

    def _import_workspace_skill_document(
        self,
        *,
        workspace_id: str,
        requested_source: str,
        source_locator: str,
        source_type: str,
        fetched: dict[str, Any],
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
    ) -> dict[str, Any]:
        detected_name = str(fetched.get("name") or "").strip()
        detected_summary = str(fetched.get("summary") or "").strip()
        content = str(fetched.get("content") or "").strip()
        source_version = str(fetched.get("source_version") or "").strip() or None
        if not content:
            raise HTTPException(status_code=422, detail="Imported skill content is empty")

        normalized_mode = _normalize_mode(mode)
        normalized_trust = _normalize_trust_level(trust_level)
        effective_name = str(name or "").strip() or detected_name or "Imported Skill"
        effective_summary = detected_summary or f"Imported from {source_locator}"
        key_candidate = str(skill_key or "").strip() or effective_name or _default_skill_key_from_url(source_locator)
        normalized_key = _normalize_skill_key(key_candidate)

        existing = self.db.execute(
            select(WorkspaceSkill).where(
                WorkspaceSkill.workspace_id == workspace_id,
                WorkspaceSkill.skill_key == normalized_key,
            )
        ).scalar_one_or_none()
        is_restore = existing is not None and bool(existing.is_deleted)
        is_update_existing = existing is not None and (not bool(existing.is_deleted))

        imported_at = datetime.now(timezone.utc).isoformat()
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest = {
            "requested_source_url": requested_source,
            "source_url": source_locator,
            "requested_source_locator": requested_source,
            "source_locator": source_locator,
            "source_version": source_version,
            "detected_name": detected_name,
            "detected_summary": detected_summary,
            "source_content": content,
            "source_content_sha256": source_hash,
            "imported_at": imported_at,
            **(fetched.get("manifest") if isinstance(fetched.get("manifest"), dict) else {}),
        }

        if existing is not None and (is_restore or is_update_existing):
            existing.name = effective_name
            existing.summary = effective_summary
            existing.source_type = source_type
            existing.source_locator = source_locator
            existing.source_version = source_version
            existing.trust_level = normalized_trust
            existing.mode = normalized_mode
            existing.manifest_json = json.dumps(manifest, ensure_ascii=True, sort_keys=True)
            existing.updated_by = self.user.id
            existing.is_deleted = False
            skill_entity = existing
        else:
            skill_entity = WorkspaceSkill(
                workspace_id=workspace_id,
                skill_key=normalized_key,
                name=effective_name,
                summary=effective_summary,
                source_type=source_type,
                source_locator=source_locator,
                source_version=source_version,
                trust_level=normalized_trust,
                mode=normalized_mode,
                manifest_json=json.dumps(manifest, ensure_ascii=True, sort_keys=True),
                is_seeded=False,
                created_by=self.user.id,
                updated_by=self.user.id,
                is_deleted=False,
            )
            self.db.add(skill_entity)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if "ux_workspace_skills_workspace_key" in str(exc):
                raise HTTPException(status_code=409, detail=f"Skill key already exists in workspace: {normalized_key}") from exc
            raise
        view = load_workspace_skill_view(self.db, skill_entity.id)
        if view is None:
            raise HTTPException(status_code=500, detail="Workspace skill was not created")
        view["already_exists"] = False
        view["updated_existing"] = bool(is_update_existing)
        view["restored_existing"] = bool(is_restore)
        return view

    def import_workspace_skill_from_url(
        self,
        *,
        workspace_id: str,
        source_url: str,
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
    ) -> dict[str, Any]:
        ensure_role(self.db, workspace_id, self.user.id, {"Owner", "Admin"})

        requested_source = str(source_url or "").strip()
        source_locator = _sanitize_source_url(source_url)
        fetched = _fetch_skill_document(source_locator)
        return self._import_workspace_skill_document(
            workspace_id=workspace_id,
            requested_source=requested_source,
            source_locator=source_locator,
            source_type="url",
            fetched=fetched,
            name=name,
            skill_key=skill_key,
            mode=mode,
            trust_level=trust_level,
        )

    def import_workspace_skill_from_file(
        self,
        *,
        workspace_id: str,
        file_name: str,
        file_content: bytes,
        file_content_type: str = "",
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
    ) -> dict[str, Any]:
        ensure_role(self.db, workspace_id, self.user.id, {"Owner", "Admin"})

        normalized_file_name = _sanitize_uploaded_filename(file_name)
        if not file_content:
            raise HTTPException(status_code=422, detail="Skill file is empty")
        source_locator = f"upload://{normalized_file_name}"
        fetched = _extract_skill_document(
            raw_bytes=file_content,
            content_type=file_content_type,
            base_manifest={
                "upload_file_name": normalized_file_name,
                "upload_content_type": str(file_content_type or "").strip(),
                "upload_size_bytes": len(file_content),
            },
        )
        return self._import_workspace_skill_document(
            workspace_id=workspace_id,
            requested_source=normalized_file_name,
            source_locator=source_locator,
            source_type="file",
            fetched=fetched,
            name=name,
            skill_key=skill_key,
            mode=mode,
            trust_level=trust_level,
        )

    def patch_workspace_skill(self, skill_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        skill = self.db.get(WorkspaceSkill, skill_id)
        if skill is None or bool(skill.is_deleted):
            raise HTTPException(status_code=404, detail="Workspace skill not found")
        ensure_role(self.db, skill.workspace_id, self.user.id, {"Owner", "Admin"})

        updates: dict[str, Any] = {}
        if "name" in patch and patch["name"] is not None:
            normalized_name = str(patch["name"]).strip()
            if not normalized_name:
                raise HTTPException(status_code=422, detail="name cannot be empty")
            updates["name"] = normalized_name
        if "summary" in patch and patch["summary"] is not None:
            updates["summary"] = str(patch["summary"])
        if "content" in patch and patch["content"] is not None:
            updates["manifest_json"] = _update_manifest_source_content(
                manifest_json=skill.manifest_json,
                source_content=str(patch["content"]),
                actor_user_id=self.user.id,
            )
        if "mode" in patch and patch["mode"] is not None:
            updates["mode"] = _normalize_mode(str(patch["mode"]))
        if "trust_level" in patch and patch["trust_level"] is not None:
            updates["trust_level"] = _normalize_trust_level(str(patch["trust_level"]))
        if not updates:
            view = load_workspace_skill_view(self.db, skill_id)
            if view is None:
                raise HTTPException(status_code=404, detail="Workspace skill not found")
            return view

        for key, value in updates.items():
            setattr(skill, key, value)
        skill.updated_by = self.user.id
        self.db.commit()
        view = load_workspace_skill_view(self.db, skill_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Workspace skill not found")
        return view

    def delete_workspace_skill(self, skill_id: str) -> dict[str, Any]:
        skill = self.db.get(WorkspaceSkill, skill_id)
        if skill is None or bool(skill.is_deleted):
            return {"ok": True}
        ensure_role(self.db, skill.workspace_id, self.user.id, {"Owner", "Admin"})
        skill.is_deleted = True
        skill.updated_by = self.user.id
        self.db.commit()
        return {"ok": True}

    def attach_workspace_skill_to_project(self, *, workspace_skill_id: str, workspace_id: str, project_id: str) -> dict[str, Any]:
        catalog_skill = self.db.get(WorkspaceSkill, workspace_skill_id)
        if catalog_skill is None or bool(catalog_skill.is_deleted):
            raise HTTPException(status_code=404, detail="Workspace skill not found")
        if str(catalog_skill.workspace_id) != str(workspace_id):
            raise HTTPException(status_code=400, detail="Workspace skill does not belong to workspace")

        ensure_role(self.db, workspace_id, self.user.id, {"Owner", "Admin", "Member"})
        ensure_project_access(self.db, workspace_id, project_id, self.user.id, {"Owner", "Admin", "Member"})
        _require_project_scope(self.db, workspace_id=workspace_id, project_id=project_id)
        created = self._attach_workspace_catalog_skill_to_project(
            catalog_skill=catalog_skill,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        dependencies = self._ensure_skill_dependencies(
            workspace_id=workspace_id,
            project_id=project_id,
            root_skill_key=str(catalog_skill.skill_key or "").strip().lower(),
            auto_apply=False,
        )
        if dependencies:
            created["resolved_dependencies"] = dependencies
            git_dependency = next((item for item in dependencies if item.get("skill_key") == _GIT_DELIVERY_SKILL_KEY), None)
            if git_dependency is not None:
                created["git_delivery_dependency"] = dict(git_dependency)
        return created

    def apply_project_skill(self, skill_id: str) -> dict[str, Any]:
        skill = self.db.get(ProjectSkill, skill_id)
        if skill is None or bool(skill.is_deleted):
            raise HTTPException(status_code=404, detail="Project skill not found")
        ensure_project_access(self.db, skill.workspace_id, skill.project_id, self.user.id, {"Owner", "Admin", "Member"})
        ensure_role(self.db, skill.workspace_id, self.user.id, {"Owner", "Admin", "Member"})
        dependencies = self._ensure_skill_dependencies(
            workspace_id=skill.workspace_id,
            project_id=skill.project_id,
            root_skill_key=str(skill.skill_key or "").strip().lower(),
            auto_apply=True,
        )

        source_content = _get_manifest_source_content(skill.manifest_json)
        if not source_content:
            raise HTTPException(status_code=422, detail="Skill source content is missing")

        generated_rule_id = self._sync_project_rule_for_skill(
            skill=skill,
            source_content=source_content,
            create_if_missing=True,
        )
        self._apply_team_mode_contract_if_needed(skill=skill)
        skill.generated_rule_id = generated_rule_id
        self._assert_generated_rule_id_uniqueness(skill=skill)
        skill.updated_by = self.user.id
        self.db.commit()
        gate_policy_rule_id = self._ensure_gate_policy_rule_if_needed(skill=skill, dependencies=dependencies)

        view = load_project_skill_view(self.db, skill_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Project skill not found")
        if gate_policy_rule_id:
            view["gate_policy_rule_id"] = gate_policy_rule_id
        if str(skill.skill_key or "").strip().lower() == _TEAM_MODE_SKILL_KEY:
            project = _require_project_scope(
                self.db,
                workspace_id=skill.workspace_id,
                project_id=skill.project_id,
            )
            roster = self._build_team_mode_roster_snapshot(project=project)
            view["team_mode_roster"] = roster
            view["team_mode_contract_complete"] = all(
                bool(item.get("user_id"))
                and bool(item.get("workspace_member_present"))
                and bool(item.get("project_member_present"))
                and str(item.get("project_member_role") or "").strip() == str(item.get("expected_project_role") or "").strip()
                for item in roster
            )
        if dependencies:
            view["resolved_dependencies"] = dependencies
            git_dependency = next((item for item in dependencies if item.get("skill_key") == _GIT_DELIVERY_SKILL_KEY), None)
            if git_dependency is not None:
                view["git_delivery_dependency"] = dict(git_dependency)
        return view

    def patch_project_skill(self, skill_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        skill = self.db.get(ProjectSkill, skill_id)
        if skill is None or bool(skill.is_deleted):
            raise HTTPException(status_code=404, detail="Project skill not found")
        ensure_project_access(self.db, skill.workspace_id, skill.project_id, self.user.id, {"Owner", "Admin", "Member"})
        ensure_role(self.db, skill.workspace_id, self.user.id, {"Owner", "Admin", "Member"})

        data = dict(patch or {})
        sync_project_rule = bool(data.pop("sync_project_rule", True))
        if "enabled" in data:
            raise HTTPException(
                status_code=422,
                detail="enabled is no longer supported for project skills; delete the skill to disable it",
            )

        updates: dict[str, Any] = {}
        if "name" in data and data["name"] is not None:
            normalized_name = str(data["name"]).strip()
            if not normalized_name:
                raise HTTPException(status_code=422, detail="name cannot be empty")
            updates["name"] = normalized_name
        if "summary" in data and data["summary"] is not None:
            updates["summary"] = str(data["summary"])
        if "content" in data and data["content"] is not None:
            updates["manifest_json"] = _update_manifest_source_content(
                manifest_json=skill.manifest_json,
                source_content=str(data["content"]),
                actor_user_id=self.user.id,
            )
        if "mode" in data and data["mode"] is not None:
            updates["mode"] = _normalize_mode(str(data["mode"]))
        if "trust_level" in data and data["trust_level"] is not None:
            updates["trust_level"] = _normalize_trust_level(str(data["trust_level"]))

        if updates:
            for key, value in updates.items():
                setattr(skill, key, value)
            skill.updated_by = self.user.id

        if sync_project_rule and skill.generated_rule_id:
            source_content = _get_manifest_source_content(skill.manifest_json)
            if source_content:
                skill.generated_rule_id = self._sync_project_rule_for_skill(
                    skill=skill,
                    source_content=source_content,
                    create_if_missing=False,
                )

        self.db.commit()
        view = load_project_skill_view(self.db, skill_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Project skill not found")
        return view

    def delete_project_skill(self, skill_id: str, *, delete_linked_rule: bool = True) -> dict[str, Any]:
        skill = self.db.get(ProjectSkill, skill_id)
        if skill is None or bool(skill.is_deleted):
            return {"ok": True}
        ensure_project_access(self.db, skill.workspace_id, skill.project_id, self.user.id, {"Owner", "Admin", "Member"})
        ensure_role(self.db, skill.workspace_id, self.user.id, {"Owner", "Admin", "Member"})

        if delete_linked_rule and skill.generated_rule_id:
            try:
                ProjectRuleApplicationService(self.db, self.user, command_id=self.command_id).delete_project_rule(
                    skill.generated_rule_id
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise

        skill.generated_rule_id = None
        skill.is_deleted = True
        skill.updated_by = self.user.id
        self.db.commit()
        return {"ok": True}
