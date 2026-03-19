from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.rules.application import ProjectRuleApplicationService
from features.specifications.application import SpecificationApplicationService
from features.tasks.application import TaskApplicationService
from shared.core import ProjectRuleCreate, ProjectSetupProfile, SpecificationCreate, TaskCreate, User, ensure_project_access

from .catalog import ProjectStarterDefinition, STARTER_VERSION, get_project_starter, list_project_facets, list_project_starters


def _serialize_starter(defn: ProjectStarterDefinition) -> dict[str, Any]:
    return {
        "key": defn.key,
        "label": defn.label,
        "description": defn.description,
        "positioning_text": defn.positioning_text,
        "recommended_use_cases": list(defn.recommended_use_cases),
        "default_custom_statuses": list(defn.default_custom_statuses),
        "retrieval_hints": list(defn.retrieval_hints),
        "question_set": list(defn.question_set),
        "setup_tags": list(defn.setup_tags),
        "facet_defaults": list(defn.facet_defaults),
        "artifact_counts": {
            "specifications": len(defn.specifications),
            "tasks": len(defn.tasks),
            "rules": len(defn.rules),
        },
    }


def _serialize_setup_profile(profile: ProjectSetupProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "project_id": profile.project_id,
        "workspace_id": profile.workspace_id,
        "primary_starter_key": str(profile.primary_starter_key or "").strip(),
        "facet_keys": json.loads(profile.facet_keys_json or "[]"),
        "starter_version": str(profile.starter_version or STARTER_VERSION),
        "resolved_inputs": json.loads(profile.resolved_inputs_json or "{}"),
        "retrieval_hints": json.loads(profile.retrieval_hints_json or "[]"),
        "applied_by": str(profile.applied_by or "").strip(),
        "applied_at": profile.created_at.isoformat() if profile.created_at else None,
    }


class ProjectStarterApplicationService:
    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user

    def list_starters(self) -> dict[str, Any]:
        return {
            "items": [_serialize_starter(item) for item in list_project_starters()],
            "facets": list_project_facets(),
        }

    def get_starter(self, starter_key: str) -> dict[str, Any]:
        definition = get_project_starter(starter_key)
        if definition is None:
            raise HTTPException(status_code=404, detail="Project starter not found")
        return _serialize_starter(definition)

    def get_setup_profile(self, project_id: str) -> dict[str, Any]:
        profile = self.db.execute(
            select(ProjectSetupProfile).where(ProjectSetupProfile.project_id == project_id)
        ).scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=404, detail="Project setup profile not found")
        ensure_project_access(
            self.db,
            profile.workspace_id,
            project_id,
            self.user.id,
            {"Owner", "Admin", "Member"},
        )
        return _serialize_setup_profile(profile) or {}

    def upsert_setup_profile(
        self,
        *,
        project_id: str,
        workspace_id: str,
        primary_starter_key: str,
        facet_keys: list[str],
        resolved_inputs: dict[str, Any],
        retrieval_hints: list[str],
    ) -> dict[str, Any]:
        profile = self.db.execute(
            select(ProjectSetupProfile).where(ProjectSetupProfile.project_id == project_id)
        ).scalar_one_or_none()
        if profile is None:
            profile = ProjectSetupProfile(
                workspace_id=workspace_id,
                project_id=project_id,
                primary_starter_key=primary_starter_key,
                facet_keys_json="[]",
                starter_version=STARTER_VERSION,
                resolved_inputs_json="{}",
                retrieval_hints_json="[]",
                applied_by=self.user.id,
            )
            self.db.add(profile)
        profile.primary_starter_key = primary_starter_key
        profile.facet_keys_json = json.dumps(facet_keys, ensure_ascii=True, sort_keys=True)
        profile.starter_version = STARTER_VERSION
        profile.resolved_inputs_json = json.dumps(resolved_inputs, ensure_ascii=True, sort_keys=True, default=str)
        profile.retrieval_hints_json = json.dumps(retrieval_hints, ensure_ascii=True, sort_keys=True)
        profile.applied_by = self.user.id
        self.db.commit()
        self.db.refresh(profile)
        return _serialize_setup_profile(profile) or {}

    def bootstrap_starter_artifacts(
        self,
        *,
        project_id: str,
        workspace_id: str,
        starter: ProjectStarterDefinition,
    ) -> dict[str, Any]:
        specification_id_by_title: dict[str, str] = {}
        created_spec_ids: list[str] = []
        created_task_ids: list[str] = []
        created_rule_ids: list[str] = []

        for item in starter.specifications:
            created = SpecificationApplicationService(self.db, self.user).create_specification(
                SpecificationCreate(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    title=item.title,
                    body=item.body,
                    status=item.status,
                )
            )
            specification_id_by_title[item.title] = str(created["id"])
            created_spec_ids.append(str(created["id"]))

        for item in starter.tasks:
            created = TaskApplicationService(self.db, self.user).create_task(
                TaskCreate(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    specification_id=specification_id_by_title.get(item.specification_title or ""),
                    title=item.title,
                    description=item.description,
                    priority=item.priority,
                    labels=list(item.labels),
                )
            )
            created_task_ids.append(str(created["id"]))

        for item in starter.rules:
            created = ProjectRuleApplicationService(self.db, self.user).create_project_rule(
                ProjectRuleCreate(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    title=item.title,
                    body=item.body,
                )
            )
            created_rule_ids.append(str(created["id"]))

        return {
            "specification_ids": created_spec_ids,
            "task_ids": created_task_ids,
            "rule_ids": created_rule_ids,
            "counts": {
                "specifications": len(created_spec_ids),
                "tasks": len(created_task_ids),
                "rules": len(created_rule_ids),
            },
        }
