from __future__ import annotations

from eventsourcing.domain import Aggregate, event

EVENT_BOUND = "ProjectTemplateBound"


class ProjectTemplateBindingAggregate(Aggregate):
    aggregate_type = "ProjectTemplateBinding"
    event_type_prefix = "ProjectTemplate"

    @event("Bound")
    def bind(
        self,
        workspace_id: str,
        project_id: str,
        template_key: str,
        template_version: str,
        applied_by: str,
        parameters_json: str,
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.template_key = template_key
        self.template_version = template_version
        self.applied_by = applied_by
        self.parameters_json = parameters_json

