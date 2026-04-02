import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from tests.core.support.runtime import build_client as build_runtime_client


def build_client(tmp_path: Path) -> TestClient:
    return build_runtime_client(
        tmp_path,
        extra_env={
            "AGENT_CODEX_WORKDIR": str(tmp_path / "workspace"),
            "AGENT_RUNNER_ENABLED": "false",
        },
    )


def test_workspace_doctor_status_seed_and_run(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    initial = client.get(f'/api/workspaces/{workspace_id}/doctor')
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert initial_payload['plugin_key'] == 'doctor'
    assert initial_payload['supported'] is True
    assert initial_payload['seeded'] is False
    runtime_health = initial_payload.get('runtime_health') or {}
    assert runtime_health.get('overall_status') in {'healthy', 'warning', 'failing'}
    assert isinstance(runtime_health.get('generated_at'), str)
    assert isinstance(runtime_health.get('health_score'), int)
    assert 0 <= int(runtime_health.get('health_score') or 0) <= 100
    domains = runtime_health.get('domains') or {}
    assert isinstance(domains.get('contracts'), dict)
    assert isinstance(domains.get('bootstrap'), dict)
    assert isinstance(domains.get('plugins'), dict)
    assert isinstance(domains.get('agent_runtime'), dict)
    assert isinstance(runtime_health.get('recommended_actions'), list)
    contracts_domain = domains.get('contracts') or {}
    contracts_metrics = contracts_domain.get('metrics') or {}
    assert isinstance(contracts_metrics.get('runtime_contract_audit_stale'), bool)
    assert contracts_metrics.get('runtime_contract_audit_stale') is True
    assert contracts_metrics.get('runtime_contract_audit_last_at') in {None, ''}
    assert contracts_metrics.get('runtime_contract_audit_age_hours') is None
    assert isinstance(contracts_metrics.get('runtime_contract_audit_stale_threshold_hours'), (int, float))
    contracts_issues = contracts_domain.get('issues') or []
    assert isinstance(contracts_issues, list)
    assert any(str(item or '').strip() == 'runtime_contract_audit_missing' for item in contracts_issues)
    recommended_action_ids = [
        str((item or {}).get('id') or '').strip()
        for item in (runtime_health.get('recommended_actions') or [])
        if isinstance(item, dict)
    ]
    assert 'runtime-contract-audit' in recommended_action_ids

    audit = client.post(f'/api/workspaces/{workspace_id}/doctor/audit')
    assert audit.status_code == 200
    audit_payload = audit.json()
    assert audit_payload.get('workspace_id') == workspace_id
    audit_summary = audit_payload.get('audit') or {}
    assert isinstance(audit_summary.get('ok'), bool)
    assert isinstance(audit_summary.get('error_count'), int)
    assert isinstance(audit_summary.get('warning_count'), int)
    assert isinstance(audit_summary.get('errors'), list)
    assert isinstance(audit_summary.get('warnings'), list)
    assert isinstance(audit_summary.get('generated_at'), str)
    assert isinstance(audit_summary.get('elapsed_ms'), int)
    assert isinstance(audit_summary.get('counts'), dict)
    assert isinstance((audit_payload.get('status') or {}).get('runtime_health'), dict)

    quick_audit = client.post(f'/api/workspaces/{workspace_id}/doctor/actions/runtime-contract-audit')
    assert quick_audit.status_code == 200
    quick_audit_payload = quick_audit.json()
    assert quick_audit_payload.get('action_id') == 'runtime-contract-audit'
    assert isinstance(quick_audit_payload.get('ok'), bool)
    assert isinstance((quick_audit_payload.get('result') or {}).get('error_count'), int)
    quick_audit_status = quick_audit_payload.get('status') or {}
    assert isinstance(quick_audit_status.get('runtime_health'), dict)
    quick_audit_runtime_health = quick_audit_status.get('runtime_health') or {}
    quick_audit_contracts = (quick_audit_runtime_health.get('domains') or {}).get('contracts') or {}
    quick_audit_metrics = quick_audit_contracts.get('metrics') or {}
    assert isinstance(quick_audit_metrics.get('runtime_contract_audit_stale'), bool)
    assert quick_audit_metrics.get('runtime_contract_audit_stale') is False
    assert isinstance(quick_audit_metrics.get('runtime_contract_audit_last_at'), str)
    assert isinstance(quick_audit_metrics.get('runtime_contract_audit_age_hours'), (int, float))
    last_action = quick_audit_status.get('last_action') or {}
    assert last_action.get('id') == 'runtime-contract-audit'
    assert isinstance(last_action.get('message'), str)
    assert isinstance(last_action.get('at'), str)
    assert isinstance(last_action.get('result'), dict)
    assert isinstance(quick_audit_status.get('last_action_at'), str)
    assert isinstance(quick_audit_status.get('last_action_result'), dict)
    recent_actions = quick_audit_status.get('recent_actions') or []
    assert isinstance(recent_actions, list)
    assert len(recent_actions) >= 1
    first_recent = recent_actions[0] if isinstance(recent_actions[0], dict) else {}
    assert isinstance(first_recent.get('id'), str)
    assert isinstance(first_recent.get('status'), str)
    assert isinstance(first_recent.get('message'), str)
    assert isinstance(first_recent.get('at'), str)
    assert isinstance(first_recent.get('result'), dict)
    action_stats = quick_audit_status.get('quick_action_stats') or {}
    assert isinstance(action_stats.get('window_hours'), int)
    assert isinstance(action_stats.get('total'), int)
    assert isinstance(action_stats.get('passed'), int)
    assert isinstance(action_stats.get('warning'), int)
    assert isinstance(action_stats.get('failed'), int)
    assert isinstance(action_stats.get('previous_total'), int)
    assert isinstance(action_stats.get('previous_passed'), int)
    assert isinstance(action_stats.get('previous_warning'), int)
    assert isinstance(action_stats.get('previous_failed'), int)
    assert isinstance(action_stats.get('delta_total'), int)
    assert isinstance(action_stats.get('delta_passed'), int)
    assert isinstance(action_stats.get('delta_warning'), int)
    assert isinstance(action_stats.get('delta_failed'), int)

    quick_warm = client.post(f'/api/workspaces/{workspace_id}/doctor/actions/warm-bootstrap-caches')
    assert quick_warm.status_code == 200
    assert quick_warm.json().get('action_id') == 'warm-bootstrap-caches'

    quick_runtime = client.post(f'/api/workspaces/{workspace_id}/doctor/actions/agent-runtime-configuration')
    assert quick_runtime.status_code == 200
    quick_runtime_payload = quick_runtime.json()
    assert quick_runtime_payload.get('action_id') == 'agent-runtime-configuration'
    assert isinstance((quick_runtime_payload.get('result') or {}).get('issues'), list)
    assert isinstance((quick_runtime_payload.get('result') or {}).get('guidance'), list)

    quick_drift = client.post(f'/api/workspaces/{workspace_id}/doctor/actions/descriptor-export-drift-check')
    assert quick_drift.status_code == 200
    quick_drift_payload = quick_drift.json()
    assert quick_drift_payload.get('action_id') == 'descriptor-export-drift-check'
    quick_drift_result = quick_drift_payload.get('result') or {}
    assert isinstance(quick_drift_result.get('descriptor_drift_detected'), bool)
    assert isinstance(quick_drift_result.get('bootstrap_descriptor_count'), int)
    assert isinstance(quick_drift_result.get('export_descriptor_count'), int)
    assert isinstance(quick_drift_result.get('debug_descriptor_count'), int)
    assert isinstance(quick_drift_result.get('missing_descriptor_count_in_export'), int)
    assert isinstance(quick_drift_result.get('missing_descriptor_count_in_debug_surface'), int)
    assert isinstance(quick_drift_result.get('issues'), list)

    quick_recovery = client.post(f'/api/workspaces/{workspace_id}/doctor/actions/recovery-sequence')
    assert quick_recovery.status_code == 200
    quick_recovery_payload = quick_recovery.json()
    assert quick_recovery_payload.get('action_id') == 'recovery-sequence'
    steps = (quick_recovery_payload.get('result') or {}).get('steps') or []
    assert isinstance(steps, list)
    assert len(steps) >= 4
    step_ids = [str((item or {}).get('id') or '').strip() for item in steps if isinstance(item, dict)]
    assert 'doctor-plugin-wiring' in step_ids
    assert 'warm-bootstrap-caches' in step_ids
    assert 'runtime-contract-audit' in step_ids
    assert 'descriptor-export-drift-check' in step_ids

    seeded = client.post(f'/api/workspaces/{workspace_id}/doctor/seed')
    assert seeded.status_code == 200
    seeded_payload = seeded.json()
    assert seeded_payload['seeded'] is True
    assert seeded_payload['project']['id']
    assert seeded_payload['checks']['team_mode_enabled'] is True
    assert seeded_payload['checks']['git_delivery_enabled'] is True
    assert seeded_payload['checks']['seeded_team_task_count'] >= 4
    seeded_runtime_health = seeded_payload.get('runtime_health') or {}
    assert seeded_runtime_health.get('overall_status') in {'healthy', 'warning', 'failing'}
    assert isinstance((seeded_runtime_health.get('domains') or {}).get('contracts'), dict)
    assert isinstance((seeded_runtime_health.get('domains') or {}).get('plugins'), dict)

    ran = client.post(f'/api/workspaces/{workspace_id}/doctor/run')
    assert ran.status_code == 200
    run_payload = ran.json()
    run = run_payload['run']
    assert run['project_id'] == seeded_payload['project']['id']
    assert run['status'] == 'passed'
    summary = run['summary']
    runtime_health_snapshot = summary.get('runtime_health_snapshot') or {}
    assert runtime_health_snapshot.get('overall_status') in {'healthy', 'warning', 'failing'}
    assert isinstance(runtime_health_snapshot.get('health_score'), int)
    assert 0 <= int(runtime_health_snapshot.get('health_score') or 0) <= 100
    assert isinstance(runtime_health_snapshot.get('domains'), dict)
    assert isinstance(runtime_health_snapshot.get('recommended_actions'), list)
    contracts_domain = (runtime_health_snapshot.get('domains') or {}).get('contracts') or {}
    contracts_metrics = contracts_domain.get('metrics') or {}
    assert isinstance(contracts_metrics.get('descriptor_drift_detected'), bool)
    assert isinstance(contracts_metrics.get('bootstrap_descriptor_count'), int)
    assert isinstance(contracts_metrics.get('export_descriptor_count'), int)
    assert isinstance(contracts_metrics.get('debug_descriptor_count'), int)
    assert isinstance(contracts_metrics.get('missing_descriptor_count_in_export'), int)
    assert isinstance(contracts_metrics.get('missing_descriptor_count_in_debug_surface'), int)
    counts = summary.get('counts') or {}
    assert int(counts.get('failed') or 0) == 0
    check_by_id = {
        str(item.get('id') or '').strip(): item
        for item in (summary.get('checks') or [])
        if isinstance(item, dict)
    }
    assert check_by_id['project_present']['status'] == 'passed'
    assert check_by_id['team_mode_enabled']['status'] == 'passed'
    assert check_by_id['git_delivery_enabled']['status'] == 'passed'
    assert check_by_id['seeded_team_tasks']['status'] == 'passed'
    assert check_by_id['team_mode_workflow']['status'] == 'passed'
    assert check_by_id['delivery_workflow']['status'] == 'passed'
    assert check_by_id['repo_context_present']['status'] == 'passed'
    assert check_by_id['git_contract_ok']['status'] == 'passed'
    assert check_by_id['compose_manifest_present']['status'] == 'passed'
    assert check_by_id['lead_deploy_decision_evidence_present']['status'] == 'passed'
    assert check_by_id['deploy_execution_evidence_present']['status'] == 'passed'
    assert check_by_id['qa_handoff_current_cycle_ok']['status'] == 'passed'
    assert check_by_id['qa_has_verifiable_artifacts']['status'] == 'passed'

    refreshed = client.get(f'/api/workspaces/{workspace_id}/doctor')
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    assert refreshed_payload['last_run'] is not None
    assert refreshed_payload['last_run_status'] == 'passed'
    assert len(refreshed_payload['recent_runs']) >= 1

    reset = client.post(f'/api/workspaces/{workspace_id}/doctor/reset')
    assert reset.status_code == 200
    reset_payload = reset.json()
    assert reset_payload['seeded'] is True
    assert reset_payload['project'] is not None
    assert reset_payload['project']['id'] == seeded_payload['project']['id']
    assert reset_payload['last_run_status'] == 'reset'


def test_workspace_doctor_seed_and_run_accept_long_command_id(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    from shared.models import CommandExecution, SessionLocal

    seed_command_id = "doctor-seed-" + ("x" * 52)
    run_command_id = "doctor-run-" + ("y" * 53)

    seeded = client.post(
        f'/api/workspaces/{workspace_id}/doctor/seed',
        headers={"X-Command-Id": seed_command_id},
    )
    assert seeded.status_code == 200
    assert seeded.json()['seeded'] is True

    ran = client.post(
        f'/api/workspaces/{workspace_id}/doctor/run',
        headers={"X-Command-Id": run_command_id},
    )
    assert ran.status_code == 200
    assert ran.json()['run']['status'] in {'passed', 'failed'}

    with SessionLocal() as db:
        command_rows = (
            db.query(CommandExecution)
            .filter(CommandExecution.command_id.like('doctor-%'))
            .all()
        )
    assert command_rows
    assert all(len(str(row.command_id or "")) <= 64 for row in command_rows)


def test_doctor_incident_recovery_and_drift_recheck_sanity_flow(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    initial = client.get(f'/api/workspaces/{workspace_id}/doctor')
    assert initial.status_code == 200
    initial_payload = initial.json()
    runtime_health = initial_payload.get('runtime_health') or {}
    assert runtime_health.get('overall_status') in {'healthy', 'warning', 'failing'}
    recommended_actions = runtime_health.get('recommended_actions') or []
    assert isinstance(recommended_actions, list)
    if str(runtime_health.get('overall_status') or '').strip().lower() in {'warning', 'failing'}:
        assert any(str((item or {}).get('id') or '').strip() == 'recovery-sequence' for item in recommended_actions if isinstance(item, dict))

    recovery = client.post(f'/api/workspaces/{workspace_id}/doctor/actions/recovery-sequence')
    assert recovery.status_code == 200
    recovery_payload = recovery.json()
    assert recovery_payload.get('action_id') == 'recovery-sequence'
    assert isinstance(recovery_payload.get('ok'), bool)
    recovery_steps = (recovery_payload.get('result') or {}).get('steps') or []
    assert isinstance(recovery_steps, list)
    assert any(str((item or {}).get('id') or '').strip() == 'runtime-contract-audit' for item in recovery_steps if isinstance(item, dict))
    assert any(str((item or {}).get('id') or '').strip() == 'descriptor-export-drift-check' for item in recovery_steps if isinstance(item, dict))

    drift_recheck = client.post(f'/api/workspaces/{workspace_id}/doctor/actions/descriptor-export-drift-check')
    assert drift_recheck.status_code == 200
    drift_payload = drift_recheck.json()
    assert drift_payload.get('action_id') == 'descriptor-export-drift-check'
    drift_result = drift_payload.get('result') or {}
    assert isinstance(drift_result.get('descriptor_drift_detected'), bool)
    assert isinstance(drift_result.get('issues'), list)

    final_status = client.get(f'/api/workspaces/{workspace_id}/doctor')
    assert final_status.status_code == 200
    final_payload = final_status.json()
    recent_actions = final_payload.get('recent_actions') or []
    assert isinstance(recent_actions, list)
    recent_action_ids = [
        str((item or {}).get('id') or '').strip()
        for item in recent_actions
        if isinstance(item, dict)
    ]
    assert 'recovery-sequence' in recent_action_ids
    assert 'descriptor-export-drift-check' in recent_action_ids
    quick_action_stats = final_payload.get('quick_action_stats') or {}
    assert isinstance(quick_action_stats.get('total'), int)
    assert int(quick_action_stats.get('total') or 0) >= 2
    contracts_domain = (((final_payload.get('runtime_health') or {}).get('domains') or {}).get('contracts') or {})
    contracts_metrics = contracts_domain.get('metrics') or {}
    assert isinstance(contracts_metrics.get('descriptor_drift_detected'), bool)


def test_project_checks_verify_exposes_team_mode_runtime_focus_summary(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    seeded = client.post(f'/api/workspaces/{workspace_id}/doctor/seed')
    assert seeded.status_code == 200
    seeded_payload = seeded.json()
    project_id = seeded_payload['project']['id']

    checks = client.get(f'/api/projects/{project_id}/checks/verify')
    assert checks.status_code == 200
    payload = checks.json()

    runtime = payload.get('team_mode_runtime') or {}
    execution_session = payload.get('team_mode_execution_session')
    automation_session_log = payload.get('team_mode_automation_session_log')
    summary = runtime.get('summary') or {}
    focus = summary.get('focus') or {}
    usage_totals = summary.get('usage_totals') or {}

    assert isinstance(focus.get('now_task_ids'), list)
    assert isinstance(focus.get('next_task_ids'), list)
    assert isinstance(focus.get('blocked_task_ids'), list)
    assert isinstance(focus.get('now_total'), int)
    assert isinstance(focus.get('next_total'), int)
    assert isinstance(focus.get('blocked_total'), int)
    assert isinstance(usage_totals.get('tasks_with_usage', 0), int)
    assert isinstance(usage_totals.get('input_tokens', 0), int)
    assert isinstance(usage_totals.get('output_tokens', 0), int)
    assert isinstance(usage_totals.get('cost_usd', 0.0), (int, float))

    assert focus['now_total'] >= len(focus['now_task_ids'])
    assert focus['next_total'] >= len(focus['next_task_ids'])
    assert focus['blocked_total'] >= len(focus['blocked_task_ids'])
    now_ids = set(str(item or '').strip() for item in focus['now_task_ids'] if str(item or '').strip())
    next_ids = set(str(item or '').strip() for item in focus['next_task_ids'] if str(item or '').strip())
    blocked_ids = set(str(item or '').strip() for item in focus['blocked_task_ids'] if str(item or '').strip())
    assert now_ids.isdisjoint(next_ids)
    assert now_ids.isdisjoint(blocked_ids)
    assert next_ids.isdisjoint(blocked_ids)

    tasks = runtime.get('tasks') or []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        runtime_state = str(task.get('runtime_state') or '').strip()
        if runtime_state in {'blocked', 'missing_instruction'}:
            blocker_code = str(task.get('blocker_code') or '').strip()
            assert blocker_code
    if execution_session is not None:
        assert isinstance(execution_session, dict)
        assert isinstance(execution_session.get('id'), str)
        assert isinstance(execution_session.get('status'), str)
        assert isinstance(execution_session.get('phase_history'), list)
        session_summary = execution_session.get('summary')
        if session_summary is not None:
            assert isinstance(session_summary, dict)
            assert isinstance(session_summary.get('verify_fix_attempts'), int)
            assert isinstance(session_summary.get('verify_fix_fix_attempt_count'), int)

    if automation_session_log is not None:
        assert isinstance(automation_session_log, dict)
        assert isinstance(automation_session_log.get('id'), str)
        assert isinstance(automation_session_log.get('status'), str)
        assert isinstance(automation_session_log.get('provider_context'), dict)
        transcript = automation_session_log.get('transcript') or []
        assert isinstance(transcript, list)
        for event in transcript:
            if not isinstance(event, dict):
                continue
            assert isinstance(event.get('event_type'), str)
            assert isinstance(event.get('index'), int)

    sessions_page = client.get(f'/api/projects/{project_id}/team-mode/execution-sessions?limit=5&offset=0')
    assert sessions_page.status_code == 200
    sessions_payload = sessions_page.json()
    assert sessions_payload.get('project_id') == project_id
    assert isinstance(sessions_payload.get('items'), list)
    assert isinstance(sessions_payload.get('total'), int)
    assert isinstance(sessions_payload.get('limit'), int)
    assert isinstance(sessions_payload.get('offset'), int)
    if sessions_payload.get('items'):
        first_item = sessions_payload['items'][0]
        assert isinstance(first_item.get('execution_session'), dict)
        assert isinstance(first_item.get('automation_session_log'), dict)
        first_execution = first_item.get('execution_session') or {}
        first_session_id = str(first_execution.get('id') or '').strip()
        if first_session_id:
            single_session = client.get(f'/api/projects/{project_id}/team-mode/execution-sessions/{first_session_id}')
            assert single_session.status_code == 200
            single_payload = single_session.json()
            assert single_payload.get('project_id') == project_id
            assert isinstance(single_payload.get('execution_session'), dict)
            assert isinstance(single_payload.get('automation_session_log'), dict)

            logs_page = client.get(f'/api/projects/{project_id}/team-mode/automation-session-logs?limit=5&offset=0')
            assert logs_page.status_code == 200
            logs_payload = logs_page.json()
            assert logs_payload.get('project_id') == project_id
            assert isinstance(logs_payload.get('items'), list)
            assert isinstance(logs_payload.get('total'), int)
            assert isinstance(logs_payload.get('limit'), int)
            assert isinstance(logs_payload.get('offset'), int)
            if logs_payload.get('items'):
                first_log = logs_payload['items'][0]
                assert isinstance(first_log, dict)
                assert isinstance(first_log.get('id'), str)
                assert isinstance(first_log.get('status'), str)
                assert isinstance(first_log.get('provider_context'), dict)
                transcript = first_log.get('transcript') or []
                assert isinstance(transcript, list)
                for event in transcript:
                    if not isinstance(event, dict):
                        continue
                    assert isinstance(event.get('event_type'), str)
                    assert isinstance(event.get('index'), int)
                    # UI replay renderer consumes label/title/summary_text if present.
                    if event.get('label') is not None:
                        assert isinstance(event.get('label'), str)
                    if event.get('title') is not None:
                        assert isinstance(event.get('title'), str)
                    if event.get('summary_text') is not None:
                        assert isinstance(event.get('summary_text'), str)
                    if str(event.get('event_type') or '').strip() == 'verify_fix':
                        assert isinstance(event.get('attempt_count'), int)
                        assert isinstance(event.get('fix_attempt_count'), int)
                        assert isinstance(event.get('runner_error_count'), int)
                        attempts = event.get('attempts') or []
                        assert isinstance(attempts, list)
                        for attempt in attempts:
                            if not isinstance(attempt, dict):
                                continue
                            if attempt.get('attempt_index') is not None:
                                assert isinstance(attempt.get('attempt_index'), int)
                            if attempt.get('status') is not None:
                                assert isinstance(attempt.get('status'), str)
                single_log = client.get(f'/api/projects/{project_id}/team-mode/automation-session-logs/{first_session_id}')
                assert single_log.status_code == 200
                single_log_payload = single_log.json()
                assert single_log_payload.get('project_id') == project_id
                assert single_log_payload.get('session_id') == first_session_id
                assert isinstance(single_log_payload.get('automation_session_log'), dict)
                single_log_row = single_log_payload.get('automation_session_log') or {}
                provider_context = single_log_row.get('provider_context') or {}
                assert isinstance(provider_context.get('provider'), str)
                assert isinstance(provider_context.get('model'), str)
                single_log_transcript = single_log_row.get('transcript') or []
                assert isinstance(single_log_transcript, list)
                for event in single_log_transcript:
                    if not isinstance(event, dict):
                        continue
                    if event.get('summary_text') is not None:
                        assert isinstance(event.get('summary_text'), str)
                    if str(event.get('event_type') or '').strip() == 'verify_fix':
                        assert isinstance(event.get('attempt_count'), int)
                        assert isinstance(event.get('fix_attempt_count'), int)
                        assert isinstance(event.get('runner_error_count'), int)


def test_team_mode_automation_session_logs_handle_legacy_rows(tmp_path: Path):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']
    actor_user_id = str((bootstrap.get('current_user') or {}).get('id') or '').strip()
    assert actor_user_id

    seeded = client.post(f'/api/workspaces/{workspace_id}/doctor/seed')
    assert seeded.status_code == 200
    project_id = seeded.json()['project']['id']

    from shared.models import SessionLocal, TeamModeExecutionSession

    with SessionLocal() as db:
        legacy = TeamModeExecutionSession(
            workspace_id=workspace_id,
            project_id=project_id,
            initiated_by=actor_user_id,
            command_id='legacy-cmd-1',
            trigger='kickoff',
            status='completed',
            phase='complete',
            phase_history_json='[]',
            queued_task_ids_json='[]',
            blocked_reasons_json='[]',
            run_summary_json=json.dumps(
                {
                    'ok': True,
                    'summary': 'Legacy summary payload',
                    'execution_provider': 'codex',
                    'execution_model': 'gpt-5',
                    'execution_reasoning_effort': 'high',
                }
            ),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(legacy)
        db.commit()
        legacy_id = str(legacy.id)

    logs_page = client.get(f'/api/projects/{project_id}/team-mode/automation-session-logs?limit=50&offset=0')
    assert logs_page.status_code == 200
    logs_payload = logs_page.json()
    items = logs_payload.get('items') or []
    assert isinstance(items, list)
    legacy_item = next((item for item in items if str((item or {}).get('id') or '').strip() == legacy_id), None)
    assert isinstance(legacy_item, dict)
    provider_context = legacy_item.get('provider_context') or {}
    assert provider_context.get('provider') == 'codex'
    assert provider_context.get('model') == 'gpt-5'
    assert provider_context.get('reasoning_effort') == 'high'
    legacy_transcript = legacy_item.get('transcript') or []
    assert isinstance(legacy_transcript, list)
    assert any(str((event or {}).get('event_type') or '').strip() == 'summary' for event in legacy_transcript if isinstance(event, dict))

    single_log = client.get(f'/api/projects/{project_id}/team-mode/automation-session-logs/{legacy_id}')
    assert single_log.status_code == 200
    single_payload = single_log.json()
    assert single_payload.get('project_id') == project_id
    assert single_payload.get('session_id') == legacy_id
    single_log_row = single_payload.get('automation_session_log') or {}
    single_provider_context = single_log_row.get('provider_context') or {}
    assert single_provider_context.get('provider') == 'codex'
    assert single_provider_context.get('model') == 'gpt-5'
    assert single_provider_context.get('reasoning_effort') == 'high'
