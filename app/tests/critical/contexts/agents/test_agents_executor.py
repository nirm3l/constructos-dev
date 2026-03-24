import subprocess

from features.agents.executor import (
    _ensure_task_worktree,
    _repo_root_changed_outside_task_worktree,
    _should_prepare_task_worktree,
)
from shared.project_repository import resolve_task_branch_name


def test_should_prepare_task_worktree_requires_team_mode_and_git_delivery():
    assert (
        _should_prepare_task_worktree(
            team_mode_enabled=False,
            git_delivery_enabled=True,
            task_status="In Progress",
            actor_project_role="DeveloperAgent",
            assignee_project_role="DeveloperAgent",
        )
        is False
    )
    assert (
        _should_prepare_task_worktree(
            team_mode_enabled=True,
            git_delivery_enabled=False,
            task_status="In Progress",
            actor_project_role="DeveloperAgent",
            assignee_project_role="DeveloperAgent",
        )
        is False
    )


def test_should_prepare_task_worktree_requires_dev_status():
    assert (
        _should_prepare_task_worktree(
            team_mode_enabled=True,
            git_delivery_enabled=True,
            task_status="In Review",
            actor_project_role="DeveloperAgent",
            assignee_project_role="DeveloperAgent",
        )
        is False
    )


def test_should_prepare_task_worktree_accepts_assignee_developer_role():
    assert (
        _should_prepare_task_worktree(
            team_mode_enabled=True,
            git_delivery_enabled=True,
            task_status="In Progress",
            actor_project_role="Owner",
            assignee_project_role="DeveloperAgent",
        )
        is True
    )


def test_should_prepare_task_worktree_accepts_actor_developer_role():
    assert (
        _should_prepare_task_worktree(
            team_mode_enabled=True,
            git_delivery_enabled=True,
            task_status="In Progress",
            actor_project_role="DeveloperAgent",
            assignee_project_role="",
        )
        is True
    )


def test_repo_root_change_check_ignores_runner_managed_artifacts_and_main_advance():
    assert (
        _repo_root_changed_outside_task_worktree(
            repo_root_before={
                "head_sha": "1111111",
                "status_entries": [],
            },
            repo_root_after={
                "head_sha": "2222222",
                "status_entries": [
                    "?? .constructos.host.compose.yml",
                    "?? .constructos/",
                ],
            },
        )
        is False
    )


def test_repo_root_change_check_still_detects_real_root_edits():
    assert (
        _repo_root_changed_outside_task_worktree(
            repo_root_before={
                "head_sha": "1111111",
                "status_entries": [],
            },
            repo_root_after={
                "head_sha": "1111111",
                "status_entries": [
                    " M src/app.js",
                ],
            },
        )
        is True
    )


def test_ensure_task_worktree_proactively_reconciles_latest_main(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-auto-sync"
    task_id = "a4adf7a7-88ba-58b2-a37f-2fe60af0d4a8"
    title = "Implement tank controls"

    worktree_path, branch_name, repo_root = _ensure_task_worktree(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )
    assert branch_name == resolve_task_branch_name(task_id=task_id, title=title)

    (repo_root / "shared-config.json").write_text('{"version":1}\n', encoding="utf-8")
    subprocess.run(["git", "add", "shared-config.json"], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "chore: update shared config on main"], cwd=str(repo_root), check=True, capture_output=True, text=True)

    _ensure_task_worktree(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )
    code, _out = subprocess.getstatusoutput(
        f"git -C {repo_root} merge-base --is-ancestor main {branch_name}"
    )
    assert code == 0
    assert (worktree_path / "shared-config.json").exists()


def test_ensure_task_worktree_skips_proactive_reconcile_when_dirty(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-auto-sync-dirty"
    task_id = "cc90eb00-e4c7-58f8-8ad5-5eb2f695ea37"
    title = "Implement enemy waves"

    worktree_path, branch_name, repo_root = _ensure_task_worktree(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )
    (worktree_path / "local-only.txt").write_text("dirty\n", encoding="utf-8")

    (repo_root / "runtime.json").write_text('{"runtime":"v2"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "runtime.json"], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "chore: update runtime metadata on main"], cwd=str(repo_root), check=True, capture_output=True, text=True)

    _ensure_task_worktree(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )
    code, _out = subprocess.getstatusoutput(
        f"git -C {repo_root} merge-base --is-ancestor main {branch_name}"
    )
    assert code != 0


def test_ensure_task_worktree_does_not_fail_when_auto_reconcile_hits_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CODEX_WORKDIR", str(tmp_path))
    project_name = "Battle City"
    project_id = "proj-auto-sync-conflict"
    task_id = "63a307de-c2f2-5fa2-b8f8-96999a05ef02"
    title = "Implement responsive HUD"

    worktree_path, branch_name, repo_root = _ensure_task_worktree(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )
    shared_file = "public/assets/styles.css"
    (worktree_path / "public" / "assets").mkdir(parents=True, exist_ok=True)
    (worktree_path / shared_file).write_text("body { color: #fff; }\n", encoding="utf-8")
    subprocess.run(["git", "add", shared_file], cwd=str(worktree_path), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: branch style update"], cwd=str(worktree_path), check=True, capture_output=True, text=True)

    subprocess.run(["git", "checkout", "main"], cwd=str(repo_root), check=True, capture_output=True, text=True)
    (repo_root / "public" / "assets").mkdir(parents=True, exist_ok=True)
    (repo_root / shared_file).write_text("body { color: #000; }\n", encoding="utf-8")
    subprocess.run(["git", "add", shared_file], cwd=str(repo_root), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "feat: main style update"], cwd=str(repo_root), check=True, capture_output=True, text=True)

    # Conflict during auto-reconcile must not abort execution setup.
    _ensure_task_worktree(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
        title=title,
    )

    code_branch_clean, out_branch_clean = subprocess.getstatusoutput(
        f"git -C {worktree_path} status --porcelain"
    )
    assert code_branch_clean == 0
    assert out_branch_clean.strip() == ""
    code_contains_main, _out_contains_main = subprocess.getstatusoutput(
        f"git -C {repo_root} merge-base --is-ancestor main {branch_name}"
    )
    assert code_contains_main != 0
