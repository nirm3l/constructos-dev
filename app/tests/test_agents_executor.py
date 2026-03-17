from features.agents.executor import _repo_root_changed_outside_task_worktree, _should_prepare_task_worktree


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
