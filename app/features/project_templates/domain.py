from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot


EVENT_BOUND = "ProjectTemplateBound"


class ProjectTemplateBindingAggregate(AggregateRoot):
    aggregate_type = "ProjectTemplateBinding"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type != EVENT_BOUND:
            raise ValueError(f"Unknown event type: {event_type}")
        self.workspace_id = str(payload.get("workspace_id") or "")
        self.project_id = str(payload.get("project_id") or "")
        self.template_key = str(payload.get("template_key") or "")
        self.template_version = str(payload.get("template_version") or "")
        self.applied_by = str(payload.get("applied_by") or "")
        self.parameters_json = str(payload.get("parameters_json") or "{}")

    def bind(
        self,
        *,
        workspace_id: str,
        project_id: str,
        template_key: str,
        template_version: str,
        applied_by: str,
        parameters_json: str,
    ) -> None:
        self.record_event(
            event_type=EVENT_BOUND,
            payload={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "template_key": template_key,
                "template_version": template_version,
                "applied_by": applied_by,
                "parameters_json": parameters_json,
            },
        )
