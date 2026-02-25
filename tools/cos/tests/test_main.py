from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from typer.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cos_cli.codex_runner import build_codex_command, toml_quote  # noqa: E402
from cos_cli.config import resolve_effective_config  # noqa: E402
from cos_cli.doctor import _collect_docker_git_auth_checks, resolve_mcp_endpoint, summarize_check_counts  # noqa: E402
from cos_cli.main import main  # noqa: E402
from cos_cli.parser import _apply_green_theme_to_chunk, app  # noqa: E402
from cos_cli.prompting import compose_prompt  # noqa: E402


def _args_stub(**overrides):
    class Stub:
        command = "chat"
        repo = ""
        model = ""
        sandbox = "workspace-write"
        approval = "on-request"
        terminal_theme = "default"
        codex_backend = "local"
        docker_container = "task-app"
        docker_workdir = "/app"
        docker_codex_binary = "codex"
        docker_codex_home_root = "/home/app/codex-home/workspace"
        docker_home = ""
        interactive_tty = True
        dangerous = False
        search = False
        json = False
        skip_git_repo_check = False
        resume_session_id = ""
        resume_last = False
        resume_all = False
        no_app_mcp = False
        app_mcp_name = "task-management-tools"
        app_mcp_url = "http://localhost:8091/mcp"
        app_mcp_bearer_env = ""

    stub = Stub()
    for key, value in overrides.items():
        setattr(stub, key, value)
    return stub


def test_toml_quote_escapes_string_content():
    quoted = toml_quote('a"b\\c')
    assert quoted == '"a\\"b\\\\c"'


def test_compose_prompt_includes_user_request_section():
    prompt = compose_prompt("system", "implement feature")
    assert "system" in prompt
    assert "User request:" in prompt
    assert "implement feature" in prompt


def test_build_codex_command_injects_app_mcp_and_prompt():
    args = _args_stub()
    prompt = "wrapped prompt"
    cmd = build_codex_command(args, prompt, [])

    assert cmd[0] == "codex"
    assert "--sandbox" in cmd
    assert "-c" in cmd
    assert cmd[-1] == prompt
    assert any("mcp_servers." in token and ".url=" in token for token in cmd)
    assert any('mcp_servers.task-management-tools.url=' in token for token in cmd)
    assert not any('mcp_servers."task-management-tools".url=' in token for token in cmd)


def test_build_codex_command_exec_adds_exec_flags():
    args = _args_stub(
        command="exec",
        json=True,
        skip_git_repo_check=True,
        search=False,
    )
    cmd = build_codex_command(args, "wrapped prompt", [])
    assert cmd[:2] == ["codex", "exec"]
    assert "--json" in cmd
    assert "--skip-git-repo-check" in cmd
    assert "--ask-for-approval" not in cmd


def test_build_codex_command_docker_exec_wraps_with_docker_exec():
    args = _args_stub(command="exec", codex_backend="docker")
    cmd = build_codex_command(args, "wrapped prompt", [])
    assert cmd[:6] == ["docker", "exec", "-i", "-w", "/app", "task-app"]
    assert cmd[6:8] == ["codex", "exec"]


def test_build_codex_command_docker_chat_requires_tty():
    args = _args_stub(command="chat", codex_backend="docker", interactive_tty=False)
    try:
        build_codex_command(args, "wrapped prompt", [])
        assert False, "Expected RuntimeError when docker chat runs without TTY"
    except RuntimeError as exc:
        assert "interactive TTY terminal" in str(exc)


def test_build_codex_command_resume_includes_last_and_session():
    args = _args_stub(command="resume", resume_last=True, resume_session_id="abc-123")
    cmd = build_codex_command(args, "continue", [])
    assert cmd[:2] == ["codex", "resume"]
    assert "--last" in cmd
    assert "abc-123" in cmd
    assert cmd[-1] == "continue"


def test_build_codex_command_docker_resume_wraps_with_tty():
    args = _args_stub(command="resume", codex_backend="docker", resume_last=True)
    cmd = build_codex_command(args, "", [])
    assert cmd[:7] == ["docker", "exec", "-i", "-t", "-w", "/app", "task-app"]
    assert cmd[7:9] == ["codex", "resume"]
    assert "--last" in cmd


def test_build_codex_command_docker_resume_sets_home_override():
    args = _args_stub(
        command="resume",
        codex_backend="docker",
        resume_session_id="abc-123",
        docker_home="/home/app/codex-home/workspace/ws/chat/chat-1",
    )
    cmd = build_codex_command(args, "", [])
    assert "-e" in cmd
    assert "HOME=/home/app/codex-home/workspace/ws/chat/chat-1" in cmd


def test_resolve_mcp_endpoint_parses_default_http_port():
    scheme, host, port = resolve_mcp_endpoint("http://localhost/mcp")
    assert scheme == "http"
    assert host == "localhost"
    assert port == 80


def test_resolve_mcp_endpoint_rejects_invalid_scheme():
    try:
        resolve_mcp_endpoint("ftp://localhost/mcp")
        assert False, "Expected ValueError for invalid scheme"
    except ValueError as exc:
        assert "http or https" in str(exc)


def test_summarize_check_counts():
    summary = summarize_check_counts(
        [
            {"status": "ok"},
            {"status": "warn"},
            {"status": "warn"},
            {"status": "fail"},
            {"status": "ignored"},
        ]
    )
    assert summary == {"ok": 1, "warn": 2, "fail": 1}


def test_collect_docker_git_auth_checks_ready(monkeypatch):
    checks: list[dict[str, str]] = []
    responses = {
        ("docker", "exec", "task-app", "git", "--version"): subprocess.CompletedProcess(
            ["docker"], 0, stdout="git version 2.47.3\n", stderr=""
        ),
        (
            "docker",
            "exec",
            "task-app",
            "sh",
            "-lc",
            'if [ -n "${GITHUB_PAT:-}" ]; then echo set; else echo missing; fi',
        ): subprocess.CompletedProcess(["docker"], 0, stdout="set\n", stderr=""),
        (
            "docker",
            "exec",
            "task-app",
            "sh",
            "-lc",
            'p="${HOME:-/home/app}/.codex/git-askpass.sh"; if [ -x "$p" ]; then echo "$p"; fi',
        ): subprocess.CompletedProcess(["docker"], 0, stdout="/home/app/.codex/git-askpass.sh\n", stderr=""),
    }

    def fake_run(cmd, **kwargs):
        key = tuple(cmd)
        if key not in responses:
            raise AssertionError(f"Unexpected command: {cmd!r}")
        return responses[key]

    monkeypatch.setattr("cos_cli.doctor.subprocess.run", fake_run)
    _collect_docker_git_auth_checks(checks, container="task-app")
    by_name = {item["name"]: item for item in checks}
    assert by_name["git_in_docker"]["status"] == "ok"
    assert by_name["github_pat_in_docker"]["status"] == "ok"
    assert by_name["git_push_auth_in_docker"]["status"] == "ok"


def test_collect_docker_git_auth_checks_pat_missing(monkeypatch):
    checks: list[dict[str, str]] = []
    responses = {
        ("docker", "exec", "task-app", "git", "--version"): subprocess.CompletedProcess(
            ["docker"], 0, stdout="git version 2.47.3\n", stderr=""
        ),
        (
            "docker",
            "exec",
            "task-app",
            "sh",
            "-lc",
            'if [ -n "${GITHUB_PAT:-}" ]; then echo set; else echo missing; fi',
        ): subprocess.CompletedProcess(["docker"], 0, stdout="missing\n", stderr=""),
    }

    def fake_run(cmd, **kwargs):
        key = tuple(cmd)
        if key not in responses:
            raise AssertionError(f"Unexpected command: {cmd!r}")
        return responses[key]

    monkeypatch.setattr("cos_cli.doctor.subprocess.run", fake_run)
    _collect_docker_git_auth_checks(checks, container="task-app")
    by_name = {item["name"]: item for item in checks}
    assert by_name["git_in_docker"]["status"] == "ok"
    assert by_name["github_pat_in_docker"]["status"] == "warn"
    assert by_name["git_push_auth_in_docker"]["status"] == "warn"


def test_parser_version_flag_prints_version_and_exits():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip().startswith("cos ")


def test_main_returns_nonzero_when_exec_prompt_missing():
    assert main(["exec"]) == 2


def test_apply_green_theme_reapplies_after_reset():
    raw = b"prefix\x1b[0mcontent"
    patched = _apply_green_theme_to_chunk(raw)
    assert patched == b"prefix\x1b[0m\x1b[32mcontent"


def test_apply_green_theme_keeps_non_reset_sgr_untouched():
    raw = b"\x1b[1mtext"
    patched = _apply_green_theme_to_chunk(raw)
    assert patched == raw


def test_build_codex_command_rejects_invalid_mcp_server_name():
    args = _args_stub(app_mcp_name='bad name with spaces')
    try:
        build_codex_command(args, "wrapped prompt", [])
        assert False, "Expected RuntimeError for invalid MCP server name"
    except RuntimeError as exc:
        assert "must match pattern" in str(exc)


def test_resolve_effective_config_prefers_local_over_global(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    (home_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos").mkdir(parents=True)

    (home_dir / ".cos" / "config.toml").write_text(
        '[cos]\napp_mcp_url = "http://global.example/mcp"\nsandbox = "read-only"\n',
        encoding="utf-8",
    )
    (repo_dir / ".cos" / "config.toml").write_text(
        '[cos]\napp_mcp_url = "http://local.example/mcp"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home_dir))

    resolved = resolve_effective_config(repo_hint=str(repo_dir))
    assert resolved.values["app_mcp_url"] == "http://local.example/mcp"
    assert resolved.sources["app_mcp_url"] == "local_config"
    assert resolved.values["sandbox"] == "read-only"
    assert resolved.sources["sandbox"] == "global_config"


def test_config_validate_warns_for_unknown_key(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    (home_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos" / "config.toml").write_text(
        '[cos]\nunknown_key = "value"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home_dir))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate", "--repo", str(repo_dir), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["warn"] >= 1


def test_config_validate_fails_for_invalid_value(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    (home_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos" / "config.toml").write_text(
        '[cos]\nsandbox = "invalid-value"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home_dir))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate", "--repo", str(repo_dir), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["summary"]["fail"] >= 1


def test_config_validate_fails_for_invalid_terminal_theme(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    (home_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos" / "config.toml").write_text(
        '[cos]\nterminal_theme = "neon"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home_dir))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate", "--repo", str(repo_dir), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["summary"]["fail"] >= 1


def test_config_validate_fails_for_invalid_codex_backend(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    (home_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos").mkdir(parents=True)
    (repo_dir / ".cos" / "config.toml").write_text(
        '[cos]\ncodex_backend = "podman"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home_dir))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate", "--repo", str(repo_dir), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["summary"]["fail"] >= 1
