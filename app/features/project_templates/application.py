from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.projects.application import ProjectApplicationService
from features.rules.application import ProjectRuleApplicationService
from features.specifications.application import SpecificationApplicationService
from features.tasks.application import TaskApplicationService
from shared.core import (
    ProjectCreate,
    ProjectRuleCreate,
    SpecificationCreate,
    TaskCreate,
    User,
    ensure_role,
)
from shared.models import ProjectTemplateBinding

from .catalog import (
    ProjectTemplateDefinition,
    get_template_definition,
    list_template_definitions,
)
from .graph_scaffold import sync_template_graph_scaffold
from .schemas import ProjectFromTemplateCreate


def _stable_command_id(*, prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split())


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
            "graph": {
                "nodes": [asdict(item) for item in defn.graph_nodes],
                "edges": [asdict(item) for item in defn.graph_edges],
            },
        },
        "seed_counts": {
            "specifications": len(defn.specifications),
            "tasks": len(defn.tasks),
            "rules": len(defn.rules),
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
        self.db.add(binding)
        self.db.commit()
        self.db.refresh(binding)
        return binding

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

    def create_project_from_template(self, payload: ProjectFromTemplateCreate) -> dict[str, Any]:
        ensure_role(self.db, payload.workspace_id, self.user.id, {"Owner", "Admin", "Member"})
        template = get_template_definition(payload.template_key)
        if template is None:
            raise HTTPException(status_code=404, detail="Project template not found")

        resolved_embedding_enabled = (
            template.default_embedding_enabled if payload.embedding_enabled is None else bool(payload.embedding_enabled)
        )
        resolved_context_top_k = payload.context_pack_evidence_top_k
        if resolved_context_top_k is None:
            resolved_context_top_k = template.default_context_pack_evidence_top_k

        project_command_id = self.command_id or _stable_command_id(
            prefix="tpl-project-create",
            payload={
                "workspace_id": payload.workspace_id,
                "template_key": template.key,
                "name_key": _normalize_text(payload.name).casefold(),
            },
        )
        created_project = ProjectApplicationService(self.db, self.user, command_id=project_command_id).create_project(
            ProjectCreate(
                workspace_id=payload.workspace_id,
                name=payload.name,
                description=payload.description,
                custom_statuses=payload.custom_statuses or list(template.default_custom_statuses),
                member_user_ids=payload.member_user_ids,
                embedding_enabled=resolved_embedding_enabled,
                embedding_model=payload.embedding_model,
                context_pack_evidence_top_k=resolved_context_top_k,
            )
        )
        project_id = created_project["id"]

        binding = self._bind_project_to_template(
            project_id=project_id,
            workspace_id=payload.workspace_id,
            template_key=template.key,
            template_version=template.version,
            parameters=payload.parameters,
        )

        specification_id_by_title = self._seed_specifications(
            workspace_id=payload.workspace_id,
            project_id=project_id,
            template=template,
        )
        rule_ids = self._seed_rules(
            workspace_id=payload.workspace_id,
            project_id=project_id,
            template=template,
        )
        task_ids = self._seed_tasks(
            workspace_id=payload.workspace_id,
            project_id=project_id,
            template=template,
            specification_id_by_title=specification_id_by_title,
        )
        sync_template_graph_scaffold(
            project_id=project_id,
            workspace_id=payload.workspace_id,
            template=template,
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
            },
            "seeded_entity_ids": {
                "specification_ids": sorted(specification_id_by_title.values()),
                "rule_ids": sorted(rule_ids),
                "task_ids": sorted(task_ids),
            },
        }
