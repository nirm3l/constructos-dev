from __future__ import annotations

from pathlib import Path

from shared import project_repository


def test_find_project_compose_manifest_uses_default_repo_path(tmp_path, monkeypatch):
    monkeypatch.setattr(project_repository, "AGENT_WORKDIR", str(tmp_path))
    repo_root = project_repository.resolve_project_repository_path(
        project_name="Tetris",
        project_id="efb0de8a-de9b-570d-bf4a-f49bfd6b4828",
    )
    repo_root.mkdir(parents=True, exist_ok=True)
    manifest_path = repo_root / "docker-compose.yml"
    manifest_path.write_text("services:\n  app:\n    image: nginx:alpine\n", encoding="utf-8")

    resolved = project_repository.find_project_compose_manifest(
        project_name="Tetris",
        project_id="efb0de8a-de9b-570d-bf4a-f49bfd6b4828",
    )

    assert resolved == manifest_path


def test_find_project_compose_manifest_uses_project_external_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(project_repository, "AGENT_WORKDIR", str(tmp_path))
    external_repo_root = Path(tmp_path) / "external-repo"
    external_repo_root.mkdir(parents=True, exist_ok=True)
    manifest_path = external_repo_root / "compose.yaml"
    manifest_path.write_text("services:\n  app:\n    image: nginx:alpine\n", encoding="utf-8")

    resolved = project_repository.find_project_compose_manifest(
        project_name="Snake",
        project_id="efb0de8a-de9b-570d-bf4a-f49bfd6b4828",
        project_external_refs=[{"url": f"file://{external_repo_root}", "title": "Repository context"}],
    )

    assert resolved == manifest_path
