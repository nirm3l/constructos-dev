from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
from types import SimpleNamespace
from typing import Annotated, Literal

import typer

try:
    import fcntl
    import pty
    import termios
    import tty
except Exception:
    fcntl = None  # type: ignore[assignment]
    pty = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

from cos_cli import __version__
from cos_cli.codex_runner import (
    build_codex_command,
    ensure_docker_provider_home,
    find_docker_resume_context,
    find_docker_resume_home,
    require_codex_runtime,
)
from cos_cli.config import (
    DEFAULTS,
    ConfigError,
    ResolvedConfig,
    resolve_effective_config,
    validate_config_files,
)
from cos_cli.doctor import run_doctor
from cos_cli.prompting import (
    build_hidden_instruction,
    compose_prompt,
    load_text_file,
    resolve_user_prompt,
)


CHAT_EXEC_CONTEXT_SETTINGS = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
}

CONFIG_PRECEDENCE = "default < global config < local config < environment < CLI option"

_SGR_PATTERN = re.compile(rb"\x1b\[([0-9;]*)m")
_GREEN_SGR = b"\x1b[32m"
_GREEN_THEME_SETUP = (
    b"\x1b]10;#00ff00\007"
    b"\x1b]4;2;#00ff00\007"
    b"\x1b]4;10;#00ff00\007"
    b"\x1b]4;7;#00ff00\007"
    b"\x1b]4;15;#00ff00\007"
    b"\x1b[0;32m"
)
_GREEN_THEME_RESET = (
    b"\x1b[0m"
    b"\x1b]110\007"
    b"\x1b]104;2\007"
    b"\x1b]104;10\007"
    b"\x1b]104;7\007"
    b"\x1b]104;15\007"
)

_SCOPE_ENV_KEYS = (
    "MCP_DEFAULT_WORKSPACE_ID",
    "COS_WORKSPACE_ID",
)
_HAS_POSIX_TTY = all(module is not None for module in (fcntl, pty, termios, tty))
_YOLO_OPTION_NAMES = ("--yolo", "--dangerously-bypass-approvals-and-sandbox")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"cos {__version__}")
        raise typer.Exit(code=0)


def _normalize_passthrough(ctx: typer.Context) -> list[str]:
    passthrough = list(ctx.args or [])
    if passthrough[:1] == ["--"]:
        passthrough = passthrough[1:]
    return passthrough


def _resolve_runtime_config_or_exit(
    *,
    repo_hint: str | None,
    overrides: dict[str, str | None],
) -> ResolvedConfig:
    try:
        return resolve_effective_config(repo_hint=repo_hint, overrides=overrides)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


def _resolved_values_with_backend_defaults(resolved: ResolvedConfig) -> dict[str, str]:
    values = {key: str(value) for key, value in resolved.values.items()}
    backend = str(values.get("codex_backend", "")).strip().lower()
    if backend != "docker":
        return values

    if str(resolved.sources.get("app_mcp_url", "")) == "default":
        values["app_mcp_url"] = str(values.get("docker_app_mcp_url", "")).strip()

    if str(resolved.sources.get("repo", "")) == "default":
        if not str(values.get("repo", "")).strip():
            values["repo"] = str(values.get("docker_workdir", "")).strip()

    return values


def _stdout_write(data: bytes) -> None:
    try:
        os.write(sys.stdout.fileno(), data)
    except OSError:
        pass


def _copy_winsize(source_fd: int, target_fd: int) -> None:
    if not _HAS_POSIX_TTY:
        return
    try:
        window_size = fcntl.ioctl(source_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(target_fd, termios.TIOCSWINSZ, window_size)
    except OSError:
        pass


def _apply_green_theme_to_chunk(data: bytes) -> bytes:
    def _replace(match: re.Match[bytes]) -> bytes:
        params = match.group(1).decode("ascii", "ignore")
        parts = [part for part in params.split(";") if part]
        if not parts:
            return match.group(0) + _GREEN_SGR
        if any(part in {"0", "39", "37", "97"} for part in parts):
            return match.group(0) + _GREEN_SGR
        return match.group(0)

    return _SGR_PATTERN.sub(_replace, data)


def _run_with_green_pty(cmd: list[str], env: dict[str, str], cwd: str | None = None) -> int:
    if not _HAS_POSIX_TTY:
        completed = subprocess.run(cmd, check=False, env=env, cwd=cwd or None)
        return int(completed.returncode)

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        completed = subprocess.run(cmd, check=False, env=env, cwd=cwd or None)
        return int(completed.returncode)

    stdin_fd = sys.stdin.fileno()
    master_fd, slave_fd = pty.openpty()
    _copy_winsize(stdin_fd, slave_fd)

    process = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        cwd=cwd or None,
        close_fds=True,
    )
    os.close(slave_fd)

    old_tty_attrs = termios.tcgetattr(stdin_fd)
    previous_sigwinch_handler = signal.getsignal(signal.SIGWINCH)

    def _on_sigwinch(_sig: int, _frame: object) -> None:
        _copy_winsize(stdin_fd, master_fd)

    signal.signal(signal.SIGWINCH, _on_sigwinch)
    _stdout_write(_GREEN_THEME_SETUP)

    try:
        tty.setraw(stdin_fd)
        while True:
            read_fds, _, _ = select.select([master_fd, stdin_fd], [], [])
            if stdin_fd in read_fds:
                user_input = os.read(stdin_fd, 65536)
                if user_input:
                    os.write(master_fd, user_input)
            if master_fd in read_fds:
                try:
                    data = os.read(master_fd, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        data = b""
                    else:
                        raise
                if not data:
                    break
                _stdout_write(_apply_green_theme_to_chunk(data))
        return int(process.wait())
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tty_attrs)
        signal.signal(signal.SIGWINCH, previous_sigwinch_handler)
        _stdout_write(_GREEN_THEME_RESET)
        try:
            os.close(master_fd)
        except OSError:
            pass


def _read_scope_from_local_env() -> dict[str, str]:
    return {key: str(os.getenv(key, "")).strip() for key in _SCOPE_ENV_KEYS}


def _read_scope_from_docker_env(*, container: str) -> dict[str, str]:
    target = str(container or "").strip()
    if not target:
        return {}
    code = (
        "import json,os\n"
        "keys = [\n"
        "  'MCP_DEFAULT_WORKSPACE_ID',\n"
        "  'COS_WORKSPACE_ID',\n"
        "]\n"
        "print(json.dumps({k: (os.getenv(k, '') or '') for k in keys}, ensure_ascii=True))\n"
    )
    try:
        proc = subprocess.run(
            ["docker", "exec", target, "python", "-c", code],
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(str(proc.stdout or "").strip() or "{}")
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key in _SCOPE_ENV_KEYS:
        out[key] = str(payload.get(key, "") or "").strip()
    return out


def _resolve_runtime_scope(*, codex_backend: str, docker_container: str) -> dict[str, object]:
    backend = str(codex_backend or "").strip().lower()
    if backend == "docker":
        raw = _read_scope_from_docker_env(container=docker_container)
    else:
        raw = _read_scope_from_local_env()

    workspace_id = str(raw.get("COS_WORKSPACE_ID", "")).strip() or str(raw.get("MCP_DEFAULT_WORKSPACE_ID", "")).strip()

    return {
        "workspace_id": workspace_id,
    }


def _is_global_yolo_enabled(ctx: typer.Context | None) -> bool:
    if ctx is None:
        return False
    payload = ctx.obj
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("global_yolo"))


def _effective_dangerous_flag(ctx: typer.Context | None, dangerous: bool) -> bool:
    return bool(dangerous or _is_global_yolo_enabled(ctx))


def _run_codex(
    *,
    command: str,
    prompt: str,
    resume_session_id: str,
    resume_last: bool,
    resume_all: bool,
    passthrough: list[str],
    repo: str,
    model: str,
    sandbox: str,
    approval: str,
    terminal_theme: str,
    provider: str,
    codex_backend: str,
    docker_container: str,
    docker_workdir: str,
    docker_codex_binary: str,
    docker_codex_home_root: str,
    docker_claude_binary: str,
    docker_claude_home_root: str,
    docker_opencode_binary: str,
    docker_opencode_home_root: str,
    dangerous: bool,
    app_mcp_name: str,
    app_mcp_url: str,
    app_mcp_bearer_env: str,
    system_prompt_file: str,
    no_app_mcp: bool,
    search: bool,
    json_output: bool,
    skip_git_repo_check: bool,
) -> int:
    try:
        prompt_path = Path(str(system_prompt_file or "")).expanduser()
        extra_system_prompt = load_text_file(prompt_path)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        return 1

    runtime_scope = _resolve_runtime_scope(
        codex_backend=str(codex_backend or ""),
        docker_container=str(docker_container or ""),
    )

    user_prompt = resolve_user_prompt(str(prompt or ""), allow_stdin=True)
    if command == "exec" and not user_prompt:
        typer.echo("`cos exec` requires a prompt (argument or stdin via '-').", err=True)
        return 2
    if command == "resume":
        wrapped_prompt = user_prompt
    else:
        has_user_prompt = bool(user_prompt)
        hidden_instruction = build_hidden_instruction(
            app_mcp_name=app_mcp_name,
            app_mcp_url=app_mcp_url,
            extra_system_prompt=extra_system_prompt,
            has_user_prompt=has_user_prompt,
            runtime_workspace_id=str(runtime_scope.get("workspace_id", "") or ""),
        )
        wrapped_prompt = compose_prompt(hidden_instruction=hidden_instruction, user_prompt=user_prompt)

    effective_skip_git_repo_check = bool(skip_git_repo_check)
    if (
        command == "exec"
        and str(provider).strip().lower() == "codex"
        and str(codex_backend).strip().lower() == "docker"
    ):
        effective_skip_git_repo_check = True

    docker_home = ""
    effective_docker_workdir = docker_workdir
    normalized_provider = str(provider or "").strip().lower() or "codex"
    if str(codex_backend).strip().lower() == "docker":
        sid = str(resume_session_id or "").strip()
        if command == "resume" and sid:
            try:
                if normalized_provider == "claude":
                    docker_resume_root = docker_claude_home_root
                elif normalized_provider == "opencode":
                    docker_resume_root = docker_opencode_home_root
                else:
                    docker_resume_root = docker_codex_home_root
                resume_context = find_docker_resume_context(
                    provider=normalized_provider,
                    container=str(docker_container or "").strip(),
                    session_id=sid,
                    search_root=str(docker_resume_root or "").strip(),
                )
                if (
                    normalized_provider == "opencode"
                    and not str(resume_context.get("home") or "").strip()
                    and str(docker_resume_root or "").strip() != "/home/app"
                ):
                    # OpenCode sessions from app chat are often stored under /home/app/.opencode.
                    resume_context = find_docker_resume_context(
                        provider=normalized_provider,
                        container=str(docker_container or "").strip(),
                        session_id=sid,
                        search_root="/home/app",
                    )
                docker_home = str(resume_context.get("home") or "").strip()
                if normalized_provider == "claude":
                    resume_cwd = str(resume_context.get("cwd") or "").strip()
                    if resume_cwd:
                        effective_docker_workdir = resume_cwd
            except RuntimeError:
                docker_home = ""
        if not docker_home:
            try:
                docker_home = ensure_docker_provider_home(
                    provider=normalized_provider,
                    container=str(docker_container or "").strip(),
                )
            except RuntimeError:
                docker_home = ""

    effective_repo = repo
    if (
        str(codex_backend).strip().lower() == "docker"
        and normalized_provider == "claude"
        and command == "resume"
        and str(effective_docker_workdir or "").strip()
    ):
        effective_repo = str(effective_docker_workdir).strip()

    args = SimpleNamespace(
        command=command,
        repo=effective_repo,
        model=model,
        sandbox=sandbox,
        approval=approval,
        dangerous=dangerous,
        provider=provider,
        search=search,
        json=json_output,
        skip_git_repo_check=effective_skip_git_repo_check,
        resume_session_id=resume_session_id,
        resume_last=resume_last,
        resume_all=resume_all,
        codex_backend=codex_backend,
        docker_container=docker_container,
        docker_workdir=effective_docker_workdir,
        docker_codex_binary=docker_codex_binary,
        docker_claude_binary=docker_claude_binary,
        docker_opencode_binary=docker_opencode_binary,
        docker_home=docker_home,
        interactive_tty=bool(sys.stdin.isatty() and sys.stdout.isatty()),
        no_app_mcp=no_app_mcp,
        app_mcp_name=app_mcp_name,
        app_mcp_url=app_mcp_url,
        app_mcp_bearer_env=app_mcp_bearer_env,
    )
    try:
        require_codex_runtime(args)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        return 1

    try:
        cmd = build_codex_command(args=args, user_prompt=wrapped_prompt, passthrough=passthrough)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        return 2

    if terminal_theme == "green" and command == "exec" and str(provider).strip().lower() == "codex":
        has_exec_color = any(token == "--color" or token.startswith("--color=") for token in cmd)
        if not has_exec_color:
            cmd[-1:-1] = ["--color", "never"]

    env = os.environ.copy()
    run_cwd = (
        str(repo or "").strip()
        if str(provider).strip().lower() in {"claude", "opencode"} and str(codex_backend).strip().lower() == "local"
        else None
    )
    if terminal_theme == "green":
        env.setdefault("NO_COLOR", "1")
        env.setdefault("CLICOLOR", "0")
        env.setdefault("CLICOLOR_FORCE", "0")
        return _run_with_green_pty(cmd=cmd, env=env, cwd=run_cwd)

    completed = subprocess.run(cmd, check=False, env=env, cwd=run_cwd)
    return int(completed.returncode)


def _run_yolo_chat_from_callback(ctx: typer.Context) -> None:
    resolved = _resolve_runtime_config_or_exit(repo_hint=None, overrides={})
    values = _resolved_values_with_backend_defaults(resolved)
    exit_code = _run_codex(
        command="chat",
        prompt="",
        resume_session_id="",
        resume_last=False,
        resume_all=False,
        passthrough=_normalize_passthrough(ctx),
        repo=str(values["repo"]),
        model=str(values["model"]),
        sandbox=str(values["sandbox"]),
        approval=str(values["approval"]),
        terminal_theme=str(values["terminal_theme"]),
        provider=str(values["provider"]),
        codex_backend=str(values["codex_backend"]),
        docker_container=str(values["docker_container"]),
        docker_workdir=str(values["docker_workdir"]),
        docker_codex_binary=str(values["docker_codex_binary"]),
        docker_codex_home_root=str(values["docker_codex_home_root"]),
        docker_claude_binary=str(values["docker_claude_binary"]),
        docker_claude_home_root=str(values["docker_claude_home_root"]),
        docker_opencode_binary=str(values["docker_opencode_binary"]),
        docker_opencode_home_root=str(values["docker_opencode_home_root"]),
        dangerous=True,
        app_mcp_name=str(values["app_mcp_name"]),
        app_mcp_url=str(values["app_mcp_url"]),
        app_mcp_bearer_env=str(values["app_mcp_bearer_env"]),
        system_prompt_file=str(values["system_prompt_file"]),
        no_app_mcp=False,
        search=False,
        json_output=False,
        skip_git_repo_check=False,
    )
    raise typer.Exit(code=exit_code)


def _summarize_checks(checks: list[dict[str, str]]) -> dict[str, int]:
    summary = {"ok": 0, "warn": 0, "fail": 0}
    for item in checks:
        status = str(item.get("status") or "").strip().lower()
        if status in summary:
            summary[status] += 1
    return summary


app = typer.Typer(
    name="cos",
    help=(
        "ConstructOS (COS) CLI for working with the ConstructOS application. "
        "It provides CLI support by running Codex, Claude Code, or OpenCode with automatic ConstructOS MCP integration."
    ),
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)

config_app = typer.Typer(
    help="Inspect and validate COS configuration for global and repository scope.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


@app.callback()
def app_callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show CLI version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    yolo: Annotated[
        bool,
        typer.Option(
            *_YOLO_OPTION_NAMES,
            help="Run Codex in YOLO mode (dangerously bypass approvals and sandbox).",
        ),
    ] = False,
) -> None:
    _ = version
    ctx.ensure_object(dict)
    if isinstance(ctx.obj, dict):
        ctx.obj["global_yolo"] = bool(yolo)
    if ctx.invoked_subcommand is None and not bool(yolo):
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)
    if bool(yolo) and ctx.invoked_subcommand is None:
        _run_yolo_chat_from_callback(ctx)


@config_app.command("show", help="Show effective COS configuration and value sources.")
def config_show_command(
    repo: Annotated[str, typer.Option("--repo", "-C", help="Repository path used to resolve local .cos/config.toml.")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Output configuration in JSON format.")] = False,
) -> None:
    resolved = _resolve_runtime_config_or_exit(repo_hint=repo or None, overrides={})
    payload = {
        "values": resolved.values,
        "sources": resolved.sources,
        "precedence": CONFIG_PRECEDENCE,
        "files": {
            "global_path": str(resolved.global_config_path),
            "global_exists": resolved.global_config_exists,
            "local_path": str(resolved.local_config_path),
            "local_exists": resolved.local_config_exists,
        },
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=True))
        return

    typer.echo("COS config (effective)")
    typer.echo(f"Precedence: {CONFIG_PRECEDENCE}")
    typer.echo("")
    for key in DEFAULTS.keys():
        value = resolved.values.get(key, "")
        source = resolved.sources.get(key, "unknown")
        typer.echo(f"- {key}: {value!r} (source: {source})")
    typer.echo("")
    typer.echo(f"- global config: {resolved.global_config_path} (exists={resolved.global_config_exists})")
    typer.echo(f"- local config: {resolved.local_config_path} (exists={resolved.local_config_exists})")


@config_app.command("validate", help="Validate global and local COS config files.")
def config_validate_command(
    repo: Annotated[str, typer.Option("--repo", "-C", help="Repository path used to resolve local .cos/config.toml.")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Output validation result in JSON format.")] = False,
) -> None:
    checks = validate_config_files(repo_hint=repo or None)
    summary = _summarize_checks(checks)
    if json_output:
        typer.echo(json.dumps({"checks": checks, "summary": summary}, ensure_ascii=True))
    else:
        typer.echo("COS config validation")
        typer.echo("")
        for item in checks:
            status = str(item.get("status") or "").strip().lower()
            symbol = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(status, "INFO")
            name = str(item.get("name") or "").strip()
            message = str(item.get("message") or "").strip()
            typer.echo(f"- [{symbol}] {name}: {message}")
        typer.echo("")
        typer.echo(f"Summary: ok={summary['ok']} warn={summary['warn']} fail={summary['fail']}")
    raise typer.Exit(code=1 if summary["fail"] > 0 else 0)


@app.command(
    "chat",
    context_settings=CHAT_EXEC_CONTEXT_SETTINGS,
    help="Start an interactive ConstructOS CLI session backed by the selected provider.",
)
def chat_command(
    ctx: typer.Context,
    prompt: Annotated[str, typer.Argument(help="Optional initial prompt. Use '-' to read from stdin.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", "-C", help="Repository directory passed to the selected provider.")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model name passed to the selected provider.")] = None,
    sandbox: Annotated[
        Literal["read-only", "workspace-write", "danger-full-access"] | None,
        typer.Option(
            "--sandbox",
            help="Sandbox policy forwarded to the selected provider.",
            case_sensitive=True,
        ),
    ] = None,
    approval: Annotated[
        Literal["untrusted", "on-request", "never"] | None,
        typer.Option(
            "--approval",
            help="Approval policy forwarded to the selected provider.",
            case_sensitive=True,
        ),
    ] = None,
    terminal_theme: Annotated[
        Literal["default", "green"] | None,
        typer.Option(
            "--terminal-theme",
            help="Terminal color theme used while running the selected provider (default or green).",
            case_sensitive=True,
        ),
    ] = None,
    provider: Annotated[
        Literal["codex", "claude", "opencode"] | None,
        typer.Option(
            "--provider",
            help="Agent CLI provider used by COS (codex, claude, or opencode).",
            case_sensitive=True,
        ),
    ] = None,
    codex_backend: Annotated[
        Literal["local", "docker"] | None,
        typer.Option(
            "--codex-backend",
            help="Runtime backend used by COS (local or docker).",
            case_sensitive=True,
        ),
    ] = None,
    docker_container: Annotated[
        str | None,
        typer.Option(
            "--docker-container",
            help="Docker container name used when --codex-backend=docker.",
        ),
    ] = None,
    docker_workdir: Annotated[
        str | None,
        typer.Option(
            "--docker-workdir",
            help="Working directory inside Docker container used for docker backend runs.",
        ),
    ] = None,
    docker_codex_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-codex-binary",
            help="Codex binary path/name inside Docker container.",
        ),
    ] = None,
    docker_claude_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-claude-binary",
            help="Claude Code binary path/name inside Docker container.",
        ),
    ] = None,
    docker_opencode_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-opencode-binary",
            help="OpenCode binary path/name inside Docker container.",
        ),
    ] = None,
    docker_codex_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-codex-home-root",
            help="Root directory in Docker used to search persisted Codex sessions for resume.",
        ),
    ] = None,
    docker_claude_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-claude-home-root",
            help="Root directory in Docker used to search persisted Claude Code sessions for resume.",
        ),
    ] = None,
    docker_opencode_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-opencode-home-root",
            help="Root directory in Docker used to search persisted OpenCode sessions for resume.",
        ),
    ] = None,
    dangerous: Annotated[
        bool,
        typer.Option("--dangerous", help="Enable the provider-specific dangerous bypass mode."),
    ] = False,
    app_mcp_name: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-name",
            help="ConstructOS application MCP server name to inject.",
        ),
    ] = None,
    app_mcp_url: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-url",
            help="ConstructOS application MCP URL to inject.",
        ),
    ] = None,
    app_mcp_bearer_env: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-bearer-env",
            help="Optional env var name for MCP bearer token (maps to bearer_token_env_var).",
        ),
    ] = None,
    system_prompt_file: Annotated[
        str | None,
        typer.Option(
            "--system-prompt-file",
            help="Optional extra hidden instructions file.",
        ),
    ] = None,
    no_app_mcp: Annotated[
        bool,
        typer.Option("--no-app-mcp", help="Do not inject application MCP override config."),
    ] = False,
    search: Annotated[bool, typer.Option("--search", help="Enable Codex web search tool when the provider supports it.")] = False,
) -> None:
    resolved = _resolve_runtime_config_or_exit(
        repo_hint=repo,
        overrides={
            "repo": repo,
            "model": model,
            "sandbox": sandbox,
            "approval": approval,
            "terminal_theme": terminal_theme,
            "provider": provider,
            "codex_backend": codex_backend,
            "docker_container": docker_container,
            "docker_workdir": docker_workdir,
            "docker_codex_binary": docker_codex_binary,
            "docker_claude_binary": docker_claude_binary,
            "docker_opencode_binary": docker_opencode_binary,
            "docker_codex_home_root": docker_codex_home_root,
            "docker_claude_home_root": docker_claude_home_root,
            "docker_opencode_home_root": docker_opencode_home_root,
            "app_mcp_name": app_mcp_name,
            "app_mcp_url": app_mcp_url,
            "app_mcp_bearer_env": app_mcp_bearer_env,
            "system_prompt_file": system_prompt_file,
        },
    )
    values = _resolved_values_with_backend_defaults(resolved)

    exit_code = _run_codex(
        command="chat",
        prompt=prompt,
        resume_session_id="",
        resume_last=False,
        resume_all=False,
        passthrough=_normalize_passthrough(ctx),
        repo=str(values["repo"]),
        model=str(values["model"]),
        sandbox=str(values["sandbox"]),
        approval=str(values["approval"]),
        terminal_theme=str(values["terminal_theme"]),
        provider=str(values["provider"]),
        codex_backend=str(values["codex_backend"]),
        docker_container=str(values["docker_container"]),
        docker_workdir=str(values["docker_workdir"]),
        docker_codex_binary=str(values["docker_codex_binary"]),
        docker_codex_home_root=str(values["docker_codex_home_root"]),
        docker_claude_binary=str(values["docker_claude_binary"]),
        docker_claude_home_root=str(values["docker_claude_home_root"]),
        docker_opencode_binary=str(values["docker_opencode_binary"]),
        docker_opencode_home_root=str(values["docker_opencode_home_root"]),
        dangerous=_effective_dangerous_flag(ctx, dangerous),
        app_mcp_name=str(values["app_mcp_name"]),
        app_mcp_url=str(values["app_mcp_url"]),
        app_mcp_bearer_env=str(values["app_mcp_bearer_env"]),
        system_prompt_file=str(values["system_prompt_file"]),
        no_app_mcp=no_app_mcp,
        search=search,
        json_output=False,
        skip_git_repo_check=False,
    )
    raise typer.Exit(code=exit_code)


@app.command(
    "exec",
    context_settings=CHAT_EXEC_CONTEXT_SETTINGS,
    help="Run non-interactive ConstructOS CLI execution backed by the selected provider.",
)
def exec_command(
    ctx: typer.Context,
    prompt: Annotated[str, typer.Argument(help="Prompt for provider execution. Use '-' to read from stdin.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", "-C", help="Repository directory passed to the selected provider.")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model name passed to the selected provider.")] = None,
    sandbox: Annotated[
        Literal["read-only", "workspace-write", "danger-full-access"] | None,
        typer.Option(
            "--sandbox",
            help="Sandbox policy forwarded to the selected provider.",
            case_sensitive=True,
        ),
    ] = None,
    approval: Annotated[
        Literal["untrusted", "on-request", "never"] | None,
        typer.Option(
            "--approval",
            help="Approval policy forwarded to the selected provider.",
            case_sensitive=True,
        ),
    ] = None,
    terminal_theme: Annotated[
        Literal["default", "green"] | None,
        typer.Option(
            "--terminal-theme",
            help="Terminal color theme used while running the selected provider (default or green).",
            case_sensitive=True,
        ),
    ] = None,
    provider: Annotated[
        Literal["codex", "claude", "opencode"] | None,
        typer.Option(
            "--provider",
            help="Agent CLI provider used by COS (codex, claude, or opencode).",
            case_sensitive=True,
        ),
    ] = None,
    codex_backend: Annotated[
        Literal["local", "docker"] | None,
        typer.Option(
            "--codex-backend",
            help="Runtime backend used by COS (local or docker).",
            case_sensitive=True,
        ),
    ] = None,
    docker_container: Annotated[
        str | None,
        typer.Option(
            "--docker-container",
            help="Docker container name used when --codex-backend=docker.",
        ),
    ] = None,
    docker_workdir: Annotated[
        str | None,
        typer.Option(
            "--docker-workdir",
            help="Working directory inside Docker container used for docker backend runs.",
        ),
    ] = None,
    docker_codex_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-codex-binary",
            help="Codex binary path/name inside Docker container.",
        ),
    ] = None,
    docker_claude_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-claude-binary",
            help="Claude Code binary path/name inside Docker container.",
        ),
    ] = None,
    docker_opencode_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-opencode-binary",
            help="OpenCode binary path/name inside Docker container.",
        ),
    ] = None,
    docker_codex_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-codex-home-root",
            help="Root directory in Docker used to search persisted Codex sessions for resume.",
        ),
    ] = None,
    docker_claude_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-claude-home-root",
            help="Root directory in Docker used to search persisted Claude Code sessions for resume.",
        ),
    ] = None,
    docker_opencode_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-opencode-home-root",
            help="Root directory in Docker used to search persisted OpenCode sessions for resume.",
        ),
    ] = None,
    dangerous: Annotated[
        bool,
        typer.Option("--dangerous", help="Enable the provider-specific dangerous bypass mode."),
    ] = False,
    app_mcp_name: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-name",
            help="ConstructOS application MCP server name to inject.",
        ),
    ] = None,
    app_mcp_url: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-url",
            help="ConstructOS application MCP URL to inject.",
        ),
    ] = None,
    app_mcp_bearer_env: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-bearer-env",
            help="Optional env var name for MCP bearer token (maps to bearer_token_env_var).",
        ),
    ] = None,
    system_prompt_file: Annotated[
        str | None,
        typer.Option(
            "--system-prompt-file",
            help="Optional extra hidden instructions file.",
        ),
    ] = None,
    no_app_mcp: Annotated[
        bool,
        typer.Option("--no-app-mcp", help="Do not inject application MCP override config."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Request JSON output when the provider supports it.")] = False,
    skip_git_repo_check: Annotated[
        bool,
        typer.Option("--skip-git-repo-check", help="Forward --skip-git-repo-check to Codex exec."),
    ] = False,
) -> None:
    resolved = _resolve_runtime_config_or_exit(
        repo_hint=repo,
        overrides={
            "repo": repo,
            "model": model,
            "sandbox": sandbox,
            "approval": approval,
            "terminal_theme": terminal_theme,
            "provider": provider,
            "codex_backend": codex_backend,
            "docker_container": docker_container,
            "docker_workdir": docker_workdir,
            "docker_codex_binary": docker_codex_binary,
            "docker_claude_binary": docker_claude_binary,
            "docker_opencode_binary": docker_opencode_binary,
            "docker_codex_home_root": docker_codex_home_root,
            "docker_claude_home_root": docker_claude_home_root,
            "docker_opencode_home_root": docker_opencode_home_root,
            "app_mcp_name": app_mcp_name,
            "app_mcp_url": app_mcp_url,
            "app_mcp_bearer_env": app_mcp_bearer_env,
            "system_prompt_file": system_prompt_file,
        },
    )
    values = _resolved_values_with_backend_defaults(resolved)

    exit_code = _run_codex(
        command="exec",
        prompt=prompt,
        resume_session_id="",
        resume_last=False,
        resume_all=False,
        passthrough=_normalize_passthrough(ctx),
        repo=str(values["repo"]),
        model=str(values["model"]),
        sandbox=str(values["sandbox"]),
        approval=str(values["approval"]),
        terminal_theme=str(values["terminal_theme"]),
        provider=str(values["provider"]),
        codex_backend=str(values["codex_backend"]),
        docker_container=str(values["docker_container"]),
        docker_workdir=str(values["docker_workdir"]),
        docker_codex_binary=str(values["docker_codex_binary"]),
        docker_codex_home_root=str(values["docker_codex_home_root"]),
        docker_claude_binary=str(values["docker_claude_binary"]),
        docker_claude_home_root=str(values["docker_claude_home_root"]),
        docker_opencode_binary=str(values["docker_opencode_binary"]),
        docker_opencode_home_root=str(values["docker_opencode_home_root"]),
        dangerous=_effective_dangerous_flag(ctx, dangerous),
        app_mcp_name=str(values["app_mcp_name"]),
        app_mcp_url=str(values["app_mcp_url"]),
        app_mcp_bearer_env=str(values["app_mcp_bearer_env"]),
        system_prompt_file=str(values["system_prompt_file"]),
        no_app_mcp=no_app_mcp,
        search=False,
        json_output=json_output,
        skip_git_repo_check=skip_git_repo_check,
    )
    raise typer.Exit(code=exit_code)


@app.command(
    "resume",
    context_settings=CHAT_EXEC_CONTEXT_SETTINGS,
    help="Resume a previous ConstructOS interactive session for the selected provider.",
)
def resume_command(
    ctx: typer.Context,
    session_id: Annotated[
        str,
        typer.Argument(help="Optional provider session/thread id. Omit to open picker or use --last."),
    ] = "",
    prompt: Annotated[
        str,
        typer.Argument(help="Optional prompt to send after resuming. Use '-' to read from stdin."),
    ] = "",
    last: Annotated[
        bool,
        typer.Option("--last", help="Resume the most recent session without showing picker."),
    ] = False,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show all sessions in picker when the provider supports it."),
    ] = False,
    repo: Annotated[str | None, typer.Option("--repo", "-C", help="Repository directory passed to the selected provider.")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model name passed to the selected provider.")] = None,
    sandbox: Annotated[
        Literal["read-only", "workspace-write", "danger-full-access"] | None,
        typer.Option(
            "--sandbox",
            help="Sandbox policy forwarded to the selected provider.",
            case_sensitive=True,
        ),
    ] = None,
    approval: Annotated[
        Literal["untrusted", "on-request", "never"] | None,
        typer.Option(
            "--approval",
            help="Approval policy forwarded to the selected provider.",
            case_sensitive=True,
        ),
    ] = None,
    terminal_theme: Annotated[
        Literal["default", "green"] | None,
        typer.Option(
            "--terminal-theme",
            help="Terminal color theme used while running the selected provider (default or green).",
            case_sensitive=True,
        ),
    ] = None,
    provider: Annotated[
        Literal["codex", "claude", "opencode"] | None,
        typer.Option(
            "--provider",
            help="Agent CLI provider used by COS (codex, claude, or opencode).",
            case_sensitive=True,
        ),
    ] = None,
    codex_backend: Annotated[
        Literal["local", "docker"] | None,
        typer.Option(
            "--codex-backend",
            help="Runtime backend used by COS (local or docker).",
            case_sensitive=True,
        ),
    ] = None,
    docker_container: Annotated[
        str | None,
        typer.Option(
            "--docker-container",
            help="Docker container name used when --codex-backend=docker.",
        ),
    ] = None,
    docker_workdir: Annotated[
        str | None,
        typer.Option(
            "--docker-workdir",
            help="Working directory inside Docker container used for docker backend runs.",
        ),
    ] = None,
    docker_codex_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-codex-binary",
            help="Codex binary path/name inside Docker container.",
        ),
    ] = None,
    docker_claude_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-claude-binary",
            help="Claude Code binary path/name inside Docker container.",
        ),
    ] = None,
    docker_opencode_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-opencode-binary",
            help="OpenCode binary path/name inside Docker container.",
        ),
    ] = None,
    docker_codex_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-codex-home-root",
            help="Root directory in Docker used to search persisted Codex sessions for resume.",
        ),
    ] = None,
    docker_claude_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-claude-home-root",
            help="Root directory in Docker used to search persisted Claude Code sessions for resume.",
        ),
    ] = None,
    docker_opencode_home_root: Annotated[
        str | None,
        typer.Option(
            "--docker-opencode-home-root",
            help="Root directory in Docker used to search persisted OpenCode sessions for resume.",
        ),
    ] = None,
    dangerous: Annotated[
        bool,
        typer.Option("--dangerous", help="Enable the provider-specific dangerous bypass mode."),
    ] = False,
    app_mcp_name: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-name",
            help="ConstructOS application MCP server name to inject.",
        ),
    ] = None,
    app_mcp_url: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-url",
            help="ConstructOS application MCP URL to inject.",
        ),
    ] = None,
    app_mcp_bearer_env: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-bearer-env",
            help="Optional env var name for MCP bearer token (maps to bearer_token_env_var).",
        ),
    ] = None,
    system_prompt_file: Annotated[
        str | None,
        typer.Option(
            "--system-prompt-file",
            help="Optional extra hidden instructions file.",
        ),
    ] = None,
    no_app_mcp: Annotated[
        bool,
        typer.Option("--no-app-mcp", help="Do not inject application MCP override config."),
    ] = False,
    search: Annotated[bool, typer.Option("--search", help="Enable Codex web search tool when the provider supports it.")] = False,
) -> None:
    if last and str(session_id or "").strip():
        typer.echo("`--last` cannot be used together with an explicit session_id.", err=True)
        raise typer.Exit(code=2)

    resolved = _resolve_runtime_config_or_exit(
        repo_hint=repo,
        overrides={
            "repo": repo,
            "model": model,
            "sandbox": sandbox,
            "approval": approval,
            "terminal_theme": terminal_theme,
            "provider": provider,
            "codex_backend": codex_backend,
            "docker_container": docker_container,
            "docker_workdir": docker_workdir,
            "docker_codex_binary": docker_codex_binary,
            "docker_claude_binary": docker_claude_binary,
            "docker_opencode_binary": docker_opencode_binary,
            "docker_codex_home_root": docker_codex_home_root,
            "docker_claude_home_root": docker_claude_home_root,
            "docker_opencode_home_root": docker_opencode_home_root,
            "app_mcp_name": app_mcp_name,
            "app_mcp_url": app_mcp_url,
            "app_mcp_bearer_env": app_mcp_bearer_env,
            "system_prompt_file": system_prompt_file,
        },
    )
    values = _resolved_values_with_backend_defaults(resolved)

    exit_code = _run_codex(
        command="resume",
        prompt=prompt,
        resume_session_id=str(session_id or "").strip(),
        resume_last=bool(last),
        resume_all=bool(show_all),
        passthrough=_normalize_passthrough(ctx),
        repo=str(values["repo"]),
        model=str(values["model"]),
        sandbox=str(values["sandbox"]),
        approval=str(values["approval"]),
        terminal_theme=str(values["terminal_theme"]),
        provider=str(values["provider"]),
        codex_backend=str(values["codex_backend"]),
        docker_container=str(values["docker_container"]),
        docker_workdir=str(values["docker_workdir"]),
        docker_codex_binary=str(values["docker_codex_binary"]),
        docker_codex_home_root=str(values["docker_codex_home_root"]),
        docker_claude_binary=str(values["docker_claude_binary"]),
        docker_claude_home_root=str(values["docker_claude_home_root"]),
        docker_opencode_binary=str(values["docker_opencode_binary"]),
        docker_opencode_home_root=str(values["docker_opencode_home_root"]),
        dangerous=_effective_dangerous_flag(ctx, dangerous),
        app_mcp_name=str(values["app_mcp_name"]),
        app_mcp_url=str(values["app_mcp_url"]),
        app_mcp_bearer_env=str(values["app_mcp_bearer_env"]),
        system_prompt_file=str(values["system_prompt_file"]),
        no_app_mcp=no_app_mcp,
        search=search,
        json_output=False,
        skip_git_repo_check=False,
    )
    raise typer.Exit(code=exit_code)


@app.command(
    "doctor",
    help="Run ConstructOS CLI diagnostics for the selected provider and ConstructOS MCP connectivity.",
)
def doctor_command(
    repo: Annotated[str | None, typer.Option("--repo", "-C", help="Repository path used to resolve local .cos/config.toml.")] = None,
    provider: Annotated[
        Literal["codex", "claude", "opencode"] | None,
        typer.Option(
            "--provider",
            help="Agent CLI provider used by COS (codex, claude, or opencode).",
            case_sensitive=True,
        ),
    ] = None,
    codex_backend: Annotated[
        Literal["local", "docker"] | None,
        typer.Option(
            "--codex-backend",
            help="Runtime backend used by COS (local or docker).",
            case_sensitive=True,
        ),
    ] = None,
    docker_container: Annotated[
        str | None,
        typer.Option(
            "--docker-container",
            help="Docker container name used when --codex-backend=docker.",
        ),
    ] = None,
    docker_codex_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-codex-binary",
            help="Codex binary path/name inside Docker container.",
        ),
    ] = None,
    docker_claude_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-claude-binary",
            help="Claude Code binary path/name inside Docker container.",
        ),
    ] = None,
    docker_opencode_binary: Annotated[
        str | None,
        typer.Option(
            "--docker-opencode-binary",
            help="OpenCode binary path/name inside Docker container.",
        ),
    ] = None,
    app_mcp_url: Annotated[
        str | None,
        typer.Option(
            "--app-mcp-url",
            help="ConstructOS application MCP URL to probe.",
        ),
    ] = None,
    app_mcp_bearer_env: Annotated[
        str | None,
        typer.Option("--app-mcp-bearer-env", help="Optional env var name for MCP bearer token."),
    ] = None,
    system_prompt_file: Annotated[
        str | None,
        typer.Option("--system-prompt-file", help="System prompt file to verify."),
    ] = None,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", help="Network timeout used for MCP probes.")] = 3.0,
    json_output: Annotated[bool, typer.Option("--json", help="Output diagnosis in JSON format.")] = False,
) -> None:
    resolved = _resolve_runtime_config_or_exit(
        repo_hint=repo,
        overrides={
            "repo": repo,
            "provider": provider,
            "codex_backend": codex_backend,
            "docker_container": docker_container,
            "docker_codex_binary": docker_codex_binary,
            "docker_claude_binary": docker_claude_binary,
            "docker_opencode_binary": docker_opencode_binary,
            "app_mcp_url": app_mcp_url,
            "app_mcp_bearer_env": app_mcp_bearer_env,
            "system_prompt_file": system_prompt_file,
        },
    )
    values = _resolved_values_with_backend_defaults(resolved)
    args = SimpleNamespace(
        provider=str(values["provider"]),
        codex_backend=str(values["codex_backend"]),
        docker_container=str(values["docker_container"]),
        docker_codex_binary=str(values["docker_codex_binary"]),
        docker_claude_binary=str(values["docker_claude_binary"]),
        docker_opencode_binary=str(values["docker_opencode_binary"]),
        app_mcp_url=str(values["app_mcp_url"]),
        app_mcp_bearer_env=str(values["app_mcp_bearer_env"]),
        system_prompt_file=str(values["system_prompt_file"]),
        timeout_seconds=timeout_seconds,
        json=json_output,
    )
    exit_code = run_doctor(args)
    raise typer.Exit(code=exit_code)
