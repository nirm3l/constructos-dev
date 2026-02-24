from shared.event_upcasters import upcast_event


def test_upcast_task_event_normalizes_optional_reference_ids():
    payload = {
        "task_group_id": "   ",
        "specification_id": "",
        "assignee_id": " user-1 ",
    }
    metadata = {"schema_version": 2}

    upgraded_payload, upgraded_meta = upcast_event("TaskCreated", payload, metadata)

    assert upgraded_payload["task_group_id"] is None
    assert upgraded_payload["specification_id"] is None
    assert upgraded_payload["assignee_id"] == "user-1"
    assert upgraded_meta["schema_version"] == 2


def test_upcast_task_event_migrates_legacy_camel_case_fields():
    payload = {
        "taskGroupId": "  ",
        "specificationId": "spec-1",
        "assigneeId": "  user-2  ",
        "projectId": "project-1",
        "priority": "Medium",
    }
    metadata = {"schema_version": 1}

    upgraded_payload, upgraded_meta = upcast_event("TaskUpdated", payload, metadata)

    assert upgraded_payload["task_group_id"] is None
    assert upgraded_payload["specification_id"] == "spec-1"
    assert upgraded_payload["assignee_id"] == "user-2"
    assert upgraded_payload["project_id"] == "project-1"
    assert upgraded_payload["priority"] == "Med"
    assert upgraded_meta["schema_version"] == 2
