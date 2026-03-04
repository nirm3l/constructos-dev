from features.agents.executor import _should_prepare_task_worktree


def test_should_prepare_task_worktree_requires_team_mode_and_git_delivery():
    assert (
        _should_prepare_task_worktree(
            team_mode_enabled=False,
            git_delivery_enabled=True,
            task_status="Dev",
            actor_project_role="DeveloperAgent",
            assignee_project_role="DeveloperAgent",
        )
        is False
    )
    assert (
        _should_prepare_task_worktree(
            team_mode_enabled=True,
            git_delivery_enabled=False,
            task_status="Dev",
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
            task_status="QA",
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
            task_status="Dev",
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
            task_status="Dev",
            actor_project_role="DeveloperAgent",
            assignee_project_role="",
        )
        is True
    )
