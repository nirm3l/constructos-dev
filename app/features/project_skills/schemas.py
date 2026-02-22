from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProjectSkillImportRequest(BaseModel):
    workspace_id: str
    project_id: str
    source_url: str = Field(min_length=1)
    name: str = ""
    skill_key: str = ""
    mode: str = "advisory"
    trust_level: str = "reviewed"


class ProjectSkillPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    summary: str | None = None
    content: str | None = None
    mode: str | None = None
    trust_level: str | None = None
    sync_project_rule: bool = True


class ProjectSkillDeleteRequest(BaseModel):
    delete_linked_rule: bool = True


class WorkspaceSkillImportRequest(BaseModel):
    workspace_id: str
    source_url: str = Field(min_length=1)
    name: str = ""
    skill_key: str = ""
    mode: str = "advisory"
    trust_level: str = "reviewed"


class WorkspaceSkillPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    summary: str | None = None
    content: str | None = None
    mode: str | None = None
    trust_level: str | None = None


class WorkspaceSkillAttachRequest(BaseModel):
    workspace_id: str
    project_id: str
