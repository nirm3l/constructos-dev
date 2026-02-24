from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, replace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.projects.application import ProjectApplicationService
from features.project_skills.application import ProjectSkillApplicationService
from features.projects.command_handlers import (
    _normalize_context_pack_evidence_top_k,
    _normalize_project_statuses,
    _project_aggregate_id,
    _resolve_project_embedding_config,
)
from features.rules.application import ProjectRuleApplicationService
from features.specifications.application import SpecificationApplicationService
from features.tasks.application import TaskApplicationService
from shared.core import (
    AggregateEventRepository,
    ProjectCreate,
    ProjectRuleCreate,
    SpecificationCreate,
    TaskCreate,
    User,
    ensure_role,
    initialize_aggregate,
)
from shared.models import Project, ProjectTemplateBinding, WorkspaceMember
from shared.chat_indexing import (
    normalize_chat_attachment_ingestion_mode,
    normalize_chat_index_mode,
)

from .catalog import (
    DDD_PRODUCT_BUILD_KEY,
    MOBILE_BROWSER_GAME_KEY,
    ProjectTemplateDefinition,
    TemplateSkill,
    get_template_definition,
    list_template_definitions,
)
from .graph_scaffold import sync_template_graph_scaffold
from .schemas import ProjectFromTemplateCreate, ProjectFromTemplatePreview
from .domain import ProjectTemplateBindingAggregate


def _stable_command_id(*, prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _append_note(text: str, note: str) -> str:
    base = str(text or "").strip()
    extra = str(note or "").strip()
    if not extra:
        return base
    if not base:
        return extra
    return f"{base}\n\n{extra}"


def _to_pascal_case(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", str(value or "").strip()) if part]
    if not parts:
        return ""
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _parameter_text(
    parameters: dict[str, Any],
    key: str,
    *,
    max_length: int = 120,
) -> str | None:
    if key not in parameters:
        return None
    normalized = _normalize_text(str(parameters.get(key) or ""))
    if not normalized:
        return None
    return normalized[:max_length]


def _parameter_int(
    parameters: dict[str, Any],
    key: str,
    *,
    min_value: int,
    max_value: int,
) -> int | None:
    if key not in parameters:
        return None
    try:
        value = int(parameters.get(key))
    except (TypeError, ValueError):
        return None
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _serialize_template(defn: ProjectTemplateDefinition) -> dict[str, Any]:
    return {
        "key": defn.key,
        "name": defn.name,
        "version": defn.version,
        "description": defn.description,
        "default_custom_statuses": list(defn.default_custom_statuses),
        "default_embedding_enabled": defn.default_embedding_enabled,
        "default_context_pack_evidence_top_k": defn.default_context_pack_evidence_top_k,
        "seed_blueprint": {
            "specifications": [asdict(item) for item in defn.specifications],
            "tasks": [asdict(item) for item in defn.tasks],
            "rules": [asdict(item) for item in defn.rules],
            "skills": [asdict(item) for item in defn.skills],
            "graph": {
                "nodes": [asdict(item) for item in defn.graph_nodes],
                "edges": [asdict(item) for item in defn.graph_edges],
            },
        },
        "seed_counts": {
            "specifications": len(defn.specifications),
            "tasks": len(defn.tasks),
            "rules": len(defn.rules),
            "skills": len(defn.skills),
            "graph_nodes": len(defn.graph_nodes),
            "graph_edges": len(defn.graph_edges),
        },
    }


def _serialize_binding(binding: ProjectTemplateBinding) -> dict[str, Any]:
    return {
        "project_id": binding.project_id,
        "workspace_id": binding.workspace_id,
        "template_key": binding.template_key,
        "template_version": binding.template_version,
        "applied_by": binding.applied_by,
        "applied_at": binding.created_at.isoformat() if binding.created_at else None,
        "parameters": json.loads(binding.parameters_json or "{}"),
    }


class ProjectTemplateApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id

    def list_templates(self) -> dict[str, Any]:
        return {"items": [_serialize_template(defn) for defn in list_template_definitions()]}

    def get_template(self, template_key: str) -> dict[str, Any]:
        definition = get_template_definition(template_key)
        if definition is None:
            raise HTTPException(status_code=404, detail="Project template not found")
        return _serialize_template(definition)

    def _resolve_template(self, template_key: str) -> ProjectTemplateDefinition:
        template = get_template_definition(template_key)
        if template is None:
            raise HTTPException(status_code=404, detail="Project template not found")
        return template

    def _resolve_seed_template(
        self,
        *,
        template: ProjectTemplateDefinition,
        parameters: dict[str, Any] | None,
    ) -> tuple[ProjectTemplateDefinition, dict[str, Any]]:
        raw_parameters = dict(parameters or {})
        if template.key == DDD_PRODUCT_BUILD_KEY:
            return self._parameterize_ddd_template(template=template, parameters=raw_parameters)
        if template.key == MOBILE_BROWSER_GAME_KEY:
            return self._parameterize_mobile_game_template(template=template, parameters=raw_parameters)
        return template, raw_parameters

    def _parameterize_ddd_template(
        self,
        *,
        template: ProjectTemplateDefinition,
        parameters: dict[str, Any],
    ) -> tuple[ProjectTemplateDefinition, dict[str, Any]]:
        domain_name = _parameter_text(parameters, "domain_name", max_length=80) or "Product"
        bounded_context_name = _parameter_text(parameters, "bounded_context_name", max_length=80) or "Core Context"
        integration_boundary_name = (
            _parameter_text(parameters, "integration_boundary_name", max_length=100)
            or "Catalog ACL Boundary"
        )
        domain_pascal = _to_pascal_case(domain_name) or "Product"

        customization_note = (
            "Customization context: "
            f"domain={domain_name}; bounded_context={bounded_context_name}; "
            f"integration_boundary={integration_boundary_name}."
        )
        specifications = tuple(
            replace(specification, body=_append_note(specification.body, customization_note))
            for specification in template.specifications
        )
        tasks = tuple(
            replace(task, description=_append_note(task.description, f"Target domain: {domain_name}."))
            for task in template.tasks
        )
        rules = tuple(
            replace(
                rule,
                body=_append_note(
                    rule.body,
                    (
                        f"Customization context: use the {domain_name} domain language consistently and "
                        f"treat {integration_boundary_name} as the external boundary."
                    ),
                ),
            )
            for rule in template.rules
        )
        node_title_overrides = {
            "bc_core": bounded_context_name,
            "agg_product": f"{domain_name} Aggregate",
            "cmd_create_product": f"Create{domain_pascal}",
            "cmd_update_product": f"Update{domain_pascal}",
            "evt_product_created": f"{domain_pascal}Created",
            "evt_product_updated": f"{domain_pascal}Updated",
            "rm_product_overview": f"{domain_name} Overview",
            "policy_unique_name": f"EnforceUnique{domain_pascal}Name",
            "boundary_catalog_acl": integration_boundary_name,
        }
        graph_nodes = tuple(
            replace(node, title=node_title_overrides.get(node.node_key, node.title))
            for node in template.graph_nodes
        )

        effective_parameters = dict(parameters)
        effective_parameters["domain_name"] = domain_name
        effective_parameters["bounded_context_name"] = bounded_context_name
        effective_parameters["integration_boundary_name"] = integration_boundary_name
        return replace(
            template,
            specifications=specifications,
            tasks=tasks,
            rules=rules,
            graph_nodes=graph_nodes,
        ), effective_parameters

    def _parameterize_mobile_game_template(
        self,
        *,
        template: ProjectTemplateDefinition,
        parameters: dict[str, Any],
    ) -> tuple[ProjectTemplateDefinition, dict[str, Any]]:
        game_name = _parameter_text(parameters, "game_name", max_length=100) or "Mobile Browser Game"
        target_device_profile = (
            _parameter_text(parameters, "target_device_profile", max_length=120)
            or "Baseline Device Profile"
        )
        deployment_target = (
            _parameter_text(parameters, "deployment_target", max_length=120)
            or "LAN QA Deployment Target"
        )
        release_environment = _parameter_text(parameters, "release_environment", max_length=80) or "LAN QA"
        qa_port = _parameter_int(parameters, "qa_port", min_value=1, max_value=65535)
        team_size = _parameter_int(parameters, "team_size", min_value=1, max_value=100)

        if team_size is None:
            team_mode_note = "Team mode: standard collaboration cadence."
        elif team_size <= 3:
            team_mode_note = "Team mode: lean team; prioritize vertical slices and minimal WIP."
        elif team_size >= 8:
            team_mode_note = "Team mode: large team; include explicit cross-team integration checkpoints."
        else:
            team_mode_note = "Team mode: balanced team; maintain steady delivery cadence."

        spec_note = (
            f"Customization context: game={game_name}; target_device_profile={target_device_profile}; "
            f"deployment_target={deployment_target}; environment={release_environment}."
        )
        specifications = tuple(
            replace(specification, body=_append_note(specification.body, spec_note))
            for specification in template.specifications
        )

        parameterized_tasks = []
        for task in template.tasks:
            extra_parts = [f"Game: {game_name}.", team_mode_note]
            lowered_title = task.title.casefold()
            if "benchmark" in lowered_title or "target devices" in lowered_title:
                extra_parts.append(f"Run on target device profile: {target_device_profile}.")
            if "deployment" in lowered_title or "compose" in lowered_title:
                port_text = f", QA port {qa_port}" if qa_port is not None else ""
                extra_parts.append(
                    f"Deploy to target: {deployment_target} ({release_environment}{port_text})."
                )
            parameterized_tasks.append(
                replace(task, description=_append_note(task.description, " ".join(extra_parts)))
            )
        tasks = tuple(parameterized_tasks)

        parameterized_rules = []
        for rule in template.rules:
            body = rule.body
            if "docker compose" in rule.title.casefold():
                port_text = f" and QA port {qa_port}" if qa_port is not None else ""
                body = _append_note(
                    body,
                    (
                        f"Deployment target override: {deployment_target} in {release_environment} "
                        f"environment{port_text}."
                    ),
                )
            else:
                body = _append_note(body, team_mode_note)
            parameterized_rules.append(replace(rule, body=body))
        rules = tuple(parameterized_rules)

        graph_node_overrides = {
            "loop_core": f"{game_name} Core Gameplay Loop",
            "device_baseline": target_device_profile,
            "deploy_lan": deployment_target,
            "release_pipeline": f"{release_environment} Compose Release Pipeline",
            "metric_retention": f"{game_name} Session Retention Metric",
        }
        graph_nodes = tuple(
            replace(node, title=graph_node_overrides.get(node.node_key, node.title))
            for node in template.graph_nodes
        )

        effective_parameters = dict(parameters)
        effective_parameters["game_name"] = game_name
        effective_parameters["target_device_profile"] = target_device_profile
        effective_parameters["deployment_target"] = deployment_target
        effective_parameters["release_environment"] = release_environment
        effective_parameters["team_size"] = team_size
        if qa_port is not None:
            effective_parameters["qa_port"] = qa_port
        return replace(
            template,
            specifications=specifications,
            tasks=tasks,
            rules=rules,
            graph_nodes=graph_nodes,
        ), effective_parameters

    def _resolve_project_blueprint(
        self,
        *,
        workspace_id: str,
        template: ProjectTemplateDefinition,
        name: str,
        custom_statuses: list[str] | None,
        member_user_ids: list[str],
        embedding_enabled: bool | None,
        embedding_model: str | None,
        context_pack_evidence_top_k: int | None,
        chat_index_mode: str | None,
        chat_attachment_ingestion_mode: str | None,
    ) -> dict[str, Any]:
        ensure_role(self.db, workspace_id, self.user.id, {"Owner", "Admin", "Member"})

        requested_members = [str(user_id).strip() for user_id in member_user_ids if str(user_id).strip()]
        deduped_member_user_ids = list(dict.fromkeys(requested_members))
        workspace_users = set(
            self.db.execute(
                select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id)
            ).scalars().all()
        )
        for user_id in deduped_member_user_ids:
            if user_id not in workspace_users:
                raise HTTPException(status_code=422, detail=f"user_id {user_id} is not a member of this workspace")

        resolved_embedding_enabled = (
            template.default_embedding_enabled if embedding_enabled is None else bool(embedding_enabled)
        )
        resolved_embedding_enabled, resolved_embedding_model = _resolve_project_embedding_config(
            embedding_enabled=resolved_embedding_enabled,
            embedding_model=embedding_model,
        )
        resolved_context_top_k = context_pack_evidence_top_k
        if resolved_context_top_k is None:
            resolved_context_top_k = template.default_context_pack_evidence_top_k
        resolved_context_top_k = _normalize_context_pack_evidence_top_k(resolved_context_top_k)
        resolved_chat_index_mode = normalize_chat_index_mode(chat_index_mode)
        resolved_chat_attachment_ingestion_mode = normalize_chat_attachment_ingestion_mode(
            chat_attachment_ingestion_mode
        )

        normalized_name = _normalize_text(name)
        project_id = _project_aggregate_id(workspace_id, normalized_name) if normalized_name else None
        conflict_status = "name_missing"
        if project_id:
            existing = self.db.get(Project, project_id)
            if existing is None:
                conflict_status = "none"
            elif bool(existing.is_deleted):
                conflict_status = "deleted"
            else:
                conflict_status = "active"

        return {
            "workspace_id": workspace_id,
            "name": normalized_name,
            "project_id": project_id,
            "custom_statuses": _normalize_project_statuses(custom_statuses or list(template.default_custom_statuses)),
            "member_user_ids": deduped_member_user_ids,
            "effective_member_user_ids": list(dict.fromkeys([self.user.id, *deduped_member_user_ids])),
            "embedding_enabled": resolved_embedding_enabled,
            "embedding_model": resolved_embedding_model,
            "context_pack_evidence_top_k": resolved_context_top_k,
            "chat_index_mode": resolved_chat_index_mode,
            "chat_attachment_ingestion_mode": resolved_chat_attachment_ingestion_mode,
            "project_conflict_status": conflict_status,
        }

    def _bind_project_to_template(
        self,
        *,
        project_id: str,
        workspace_id: str,
        template_key: str,
        template_version: str,
        parameters: dict[str, Any],
    ) -> ProjectTemplateBinding:
        existing = self.db.execute(
            select(ProjectTemplateBinding).where(ProjectTemplateBinding.project_id == project_id)
        ).scalar_one_or_none()
        if existing and existing.template_key != template_key:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Project is already bound to template {existing.template_key} "
                    f"(version {existing.template_version})"
                ),
            )
        if existing:
            return existing

        binding = ProjectTemplateBinding(
            workspace_id=workspace_id,
            project_id=project_id,
            template_key=template_key,
            template_version=template_version,
            applied_by=self.user.id,
            parameters_json=json.dumps(parameters or {}, ensure_ascii=True, sort_keys=True, default=str),
        )
        aggregate = initialize_aggregate(ProjectTemplateBindingAggregate, aggregate_id=project_id, version=0)
        aggregate.bind(
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            template_key=binding.template_key,
            template_version=binding.template_version,
            applied_by=binding.applied_by,
            parameters_json=binding.parameters_json,
        )
        AggregateEventRepository(self.db).persist(
            aggregate,
            base_metadata={
                "actor_id": self.user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
            },
            expected_version=0,
        )
        self.db.commit()
        created = self.db.execute(
            select(ProjectTemplateBinding).where(ProjectTemplateBinding.project_id == project_id)
        ).scalar_one_or_none()
        if created is None:
            raise HTTPException(status_code=500, detail="Project template binding was not created")
        return created

    def _seed_specifications(
        self,
        *,
        workspace_id: str,
        project_id: str,
        template: ProjectTemplateDefinition,
    ) -> dict[str, str]:
        specification_id_by_title: dict[str, str] = {}
        for specification in template.specifications:
            title_key = _normalize_text(specification.title).casefold()
            command_id = _stable_command_id(
                prefix="tpl-seed-spec",
                payload={
                    "project_id": project_id,
                    "template_key": template.key,
                    "template_version": template.version,
                    "title_key": title_key,
                },
            )
            payload = SpecificationCreate(
                workspace_id=workspace_id,
                project_id=project_id,
                title=specification.title,
                body=specification.body,
                status=specification.status,
            )
            created = SpecificationApplicationService(self.db, self.user, command_id=command_id).create_specification(payload)
            specification_id_by_title[specification.title] = created["id"]
        return specification_id_by_title

    def _seed_rules(
        self,
        *,
        workspace_id: str,
        project_id: str,
        template: ProjectTemplateDefinition,
    ) -> list[str]:
        created_rule_ids: list[str] = []
        for rule in template.rules:
            title_key = _normalize_text(rule.title).casefold()
            command_id = _stable_command_id(
                prefix="tpl-seed-rule",
                payload={
                    "project_id": project_id,
                    "template_key": template.key,
                    "template_version": template.version,
                    "title_key": title_key,
                },
            )
            payload = ProjectRuleCreate(
                workspace_id=workspace_id,
                project_id=project_id,
                title=rule.title,
                body=rule.body,
            )
            created = ProjectRuleApplicationService(self.db, self.user, command_id=command_id).create_project_rule(payload)
            created_rule_ids.append(created["id"])
        return created_rule_ids

    def _seed_tasks(
        self,
        *,
        workspace_id: str,
        project_id: str,
        template: ProjectTemplateDefinition,
        specification_id_by_title: dict[str, str],
    ) -> list[str]:
        created_task_ids: list[str] = []
        for task in template.tasks:
            specification_id: str | None = None
            if task.specification_title:
                specification_id = specification_id_by_title.get(task.specification_title)
                if not specification_id:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Template task references unknown specification: {task.specification_title}",
                    )

            title_key = _normalize_text(task.title).casefold()
            command_id = _stable_command_id(
                prefix="tpl-seed-task",
                payload={
                    "project_id": project_id,
                    "template_key": template.key,
                    "template_version": template.version,
                    "title_key": title_key,
                },
            )
            payload = TaskCreate(
                workspace_id=workspace_id,
                project_id=project_id,
                specification_id=specification_id,
                title=task.title,
                description=task.description,
                priority=task.priority,
                labels=list(task.labels),
            )
            created = TaskApplicationService(self.db, self.user, command_id=command_id).create_task(payload)
            created_task_ids.append(created["id"])
        return created_task_ids

    def _seed_skills(
        self,
        *,
        workspace_id: str,
        project_id: str,
        template: ProjectTemplateDefinition,
    ) -> dict[str, Any]:
        created_skill_ids: list[str] = []
        generated_rule_ids: list[str] = []
        skipped: list[dict[str, str]] = []
        for skill in template.skills:
            if not isinstance(skill, TemplateSkill):
                continue
            source_url = str(skill.source_url or "").strip()
            if not source_url:
                if skill.required:
                    raise HTTPException(status_code=422, detail="Template skill source_url cannot be empty")
                skipped.append(
                    {
                        "skill_key": str(skill.skill_key or "").strip(),
                        "name": str(skill.name or "").strip(),
                        "source_url": "",
                        "reason": "Template skill source_url is empty",
                    }
                )
                continue

            normalized_key = _normalize_text(skill.skill_key).replace(" ", "_").lower()
            command_id = _stable_command_id(
                prefix="tpl-seed-skill",
                payload={
                    "project_id": project_id,
                    "template_key": template.key,
                    "template_version": template.version,
                    "skill_key": normalized_key,
                    "source_url": source_url,
                },
            )
            try:
                created = ProjectSkillApplicationService(self.db, self.user, command_id=command_id).import_skill_from_url(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    source_url=source_url,
                    name=skill.name,
                    skill_key=skill.skill_key,
                    mode=skill.mode,
                    trust_level=skill.trust_level,
                )
            except HTTPException as exc:
                if skill.required:
                    raise
                detail_value = exc.detail
                reason = str(detail_value if isinstance(detail_value, str) else json.dumps(detail_value, ensure_ascii=True))
                skipped.append(
                    {
                        "skill_key": str(skill.skill_key or "").strip(),
                        "name": str(skill.name or "").strip(),
                        "source_url": source_url,
                        "reason": reason[:500],
                    }
                )
                continue
            except Exception as exc:
                if skill.required:
                    raise HTTPException(status_code=422, detail=f"Template skill import failed: {exc}") from exc
                skipped.append(
                    {
                        "skill_key": str(skill.skill_key or "").strip(),
                        "name": str(skill.name or "").strip(),
                        "source_url": source_url,
                        "reason": str(exc)[:500],
                    }
                )
                continue

            skill_id = str(created.get("id") or "").strip()
            generated_rule_id = str(created.get("generated_rule_id") or "").strip()
            if skill_id:
                created_skill_ids.append(skill_id)
            if generated_rule_id:
                generated_rule_ids.append(generated_rule_id)
        return {
            "project_skill_ids": list(dict.fromkeys(created_skill_ids)),
            "project_skill_rule_ids": list(dict.fromkeys(generated_rule_ids)),
            "skipped": skipped,
        }

    def preview_project_from_template(self, payload: ProjectFromTemplatePreview) -> dict[str, Any]:
        template = self._resolve_template(payload.template_key)
        seed_template, effective_parameters = self._resolve_seed_template(
            template=template,
            parameters=payload.parameters,
        )
        resolved = self._resolve_project_blueprint(
            workspace_id=payload.workspace_id,
            template=template,
            name=payload.name,
            custom_statuses=payload.custom_statuses,
            member_user_ids=payload.member_user_ids,
            embedding_enabled=payload.embedding_enabled,
            embedding_model=payload.embedding_model,
            context_pack_evidence_top_k=payload.context_pack_evidence_top_k,
            chat_index_mode=payload.chat_index_mode,
            chat_attachment_ingestion_mode=payload.chat_attachment_ingestion_mode,
        )
        graph_node_count = len(seed_template.graph_nodes)
        graph_edge_count = len(seed_template.graph_edges)
        return {
            "mode": "preview",
            "template": {
                "key": template.key,
                "name": template.name,
                "version": template.version,
                "description": template.description,
            },
            "project_blueprint": {
                "workspace_id": payload.workspace_id,
                "project_id": resolved["project_id"],
                "name": resolved["name"],
                "description": payload.description,
                "custom_statuses": resolved["custom_statuses"],
                "member_user_ids": resolved["member_user_ids"],
                "effective_member_user_ids": resolved["effective_member_user_ids"],
                "embedding_enabled": resolved["embedding_enabled"],
                "embedding_model": resolved["embedding_model"],
                "context_pack_evidence_top_k": resolved["context_pack_evidence_top_k"],
                "chat_index_mode": resolved["chat_index_mode"],
                "chat_attachment_ingestion_mode": resolved["chat_attachment_ingestion_mode"],
            },
            "binding_preview": {
                "workspace_id": payload.workspace_id,
                "project_id": resolved["project_id"],
                "template_key": template.key,
                "template_version": template.version,
                "applied_by": self.user.id,
                "parameters": effective_parameters,
            },
            "seed_summary": {
                "specification_count": len(seed_template.specifications),
                "rule_count": len(seed_template.rules),
                "task_count": len(seed_template.tasks),
                "skill_count": len(seed_template.skills),
                "graph_node_count": graph_node_count,
                "graph_edge_count": graph_edge_count,
            },
            "seed_blueprint": {
                "specifications": [asdict(item) for item in seed_template.specifications],
                "tasks": [asdict(item) for item in seed_template.tasks],
                "rules": [asdict(item) for item in seed_template.rules],
                "skills": [asdict(item) for item in seed_template.skills],
                "graph": {
                    "nodes": [asdict(item) for item in seed_template.graph_nodes],
                    "edges": [asdict(item) for item in seed_template.graph_edges],
                },
            },
            "graph_scaffold_summary": {
                "template_node_id": f"template:{template.key}",
                "template_version_node_id": f"template:{template.key}@{template.version}",
                "project_relation_types": [
                    "USES_TEMPLATE",
                    "USES_TEMPLATE_VERSION",
                    "VERSION_OF",
                ],
                "graph_node_count": graph_node_count,
                "graph_edge_count": graph_edge_count,
            },
            "project_conflict": {
                "status": resolved["project_conflict_status"],
                "can_create": resolved["project_conflict_status"] == "none",
            },
        }

    def create_project_from_template(self, payload: ProjectFromTemplateCreate) -> dict[str, Any]:
        template = self._resolve_template(payload.template_key)
        seed_template, effective_parameters = self._resolve_seed_template(
            template=template,
            parameters=payload.parameters,
        )
        resolved = self._resolve_project_blueprint(
            workspace_id=payload.workspace_id,
            template=template,
            name=payload.name,
            custom_statuses=payload.custom_statuses,
            member_user_ids=payload.member_user_ids,
            embedding_enabled=payload.embedding_enabled,
            embedding_model=payload.embedding_model,
            context_pack_evidence_top_k=payload.context_pack_evidence_top_k,
            chat_index_mode=payload.chat_index_mode,
            chat_attachment_ingestion_mode=payload.chat_attachment_ingestion_mode,
        )

        project_command_id = self.command_id or _stable_command_id(
            prefix="tpl-project-create",
            payload={
                "workspace_id": payload.workspace_id,
                "template_key": template.key,
                "name_key": str(resolved["name"]).casefold(),
            },
        )
        created_project = ProjectApplicationService(self.db, self.user, command_id=project_command_id).create_project(
            ProjectCreate(
                workspace_id=payload.workspace_id,
                name=str(resolved["name"]),
                description=payload.description,
                custom_statuses=list(resolved["custom_statuses"]),
                member_user_ids=list(resolved["member_user_ids"]),
                embedding_enabled=bool(resolved["embedding_enabled"]),
                embedding_model=resolved["embedding_model"],
                context_pack_evidence_top_k=resolved["context_pack_evidence_top_k"],
                chat_index_mode=resolved["chat_index_mode"],
                chat_attachment_ingestion_mode=resolved["chat_attachment_ingestion_mode"],
            )
        )
        project_id = created_project["id"]

        binding = self._bind_project_to_template(
            project_id=project_id,
            workspace_id=payload.workspace_id,
            template_key=template.key,
            template_version=template.version,
            parameters=effective_parameters,
        )

        specification_id_by_title = self._seed_specifications(
            workspace_id=payload.workspace_id,
            project_id=project_id,
            template=seed_template,
        )
        rule_ids = self._seed_rules(
            workspace_id=payload.workspace_id,
            project_id=project_id,
            template=seed_template,
        )
        task_ids = self._seed_tasks(
            workspace_id=payload.workspace_id,
            project_id=project_id,
            template=seed_template,
            specification_id_by_title=specification_id_by_title,
        )
        skill_seed = self._seed_skills(
            workspace_id=payload.workspace_id,
            project_id=project_id,
            template=seed_template,
        )
        sync_template_graph_scaffold(
            project_id=project_id,
            workspace_id=payload.workspace_id,
            template=seed_template,
        )

        return {
            "project": created_project,
            "template": {
                "key": template.key,
                "name": template.name,
                "version": template.version,
            },
            "binding": _serialize_binding(binding),
            "seed_summary": {
                "specification_count": len(specification_id_by_title),
                "rule_count": len(rule_ids),
                "task_count": len(task_ids),
                "skill_count": len(skill_seed["project_skill_ids"]),
                "skill_skip_count": len(skill_seed["skipped"]),
            },
            "seeded_entity_ids": {
                "specification_ids": sorted(specification_id_by_title.values()),
                "rule_ids": sorted(rule_ids),
                "task_ids": sorted(task_ids),
                "project_skill_ids": sorted(skill_seed["project_skill_ids"]),
                "project_skill_rule_ids": sorted(skill_seed["project_skill_rule_ids"]),
            },
            "skill_seed_report": {
                "skipped": skill_seed["skipped"],
            },
        }
