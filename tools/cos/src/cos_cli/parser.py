from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Annotated, Literal

import typer

from cos_cli import __version__
from cos_cli.codex_runner import build_codex_command, require_codex_binary
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


def _run_codex(
    *,
    command: str,
    prompt: str,
    passthrough: list[str],
    repo: str,
    model: str,
    sandbox: str,
    approval: str,
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
        require_codex_binary()
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        return 1

    user_prompt = resolve_user_prompt(str(prompt or ""), allow_stdin=True)
    if command == "exec" and not user_prompt:
        typer.echo("`cos exec` requires a prompt (argument or stdin via '-').", err=True)
        return 2
    has_user_prompt = bool(user_prompt)

    hidden_instruction = build_hidden_instruction(
        app_mcp_name=app_mcp_name,
        app_mcp_url=app_mcp_url,
        extra_system_prompt=extra_system_prompt,
        has_user_prompt=has_user_prompt,
    )
    wrapped_prompt = compose_prompt(hidden_instruction=hidden_instruction, user_prompt=user_prompt)

    args = SimpleNamespace(
        command=command,
        repo=repo,
        model=model,
        sandbox=sandbox,
        approval=approval,
        dangerous=dangerous,
        search=search,
        json=json_output,
        skip_git_repo_check=skip_git_repo_check,
        no_app_mcp=no_app_mcp,
        app_mcp_name=app_mcp_name,
        app_mcp_url=app_mcp_url,
        app_mcp_bearer_env=app_mcp_bearer_env,
    )
    cmd = build_codex_command(args=args, user_prompt=wrapped_prompt, passthrough=passthrough)
    completed = subprocess.run(cmd, check=False)
    return int(completed.returncode)


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
        "It provides CLI support by running Codex with automatic ConstructOS MCP integration."
    ),
    add_completion=False,
    no_args_is_help=True,
)

config_app = typer.Typer(
    help="Inspect and validate COS configuration for global and repository scope.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


@app.callback()
def app_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show CLI version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    _ = version


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
    help="Start an interactive ConstructOS CLI session backed by Codex.",
)
def chat_command(
    ctx: typer.Context,
    prompt: Annotated[str, typer.Argument(help="Optional initial prompt. Use '-' to read from stdin.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", "-C", help="Repository directory passed to Codex with --cd.")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Codex model (passed as -m).")] = None,
    sandbox: Annotated[
        Literal["read-only", "workspace-write", "danger-full-access"] | None,
        typer.Option(
            "--sandbox",
            help="Sandbox policy forwarded to Codex.",
            case_sensitive=True,
        ),
    ] = None,
    approval: Annotated[
        Literal["untrusted", "on-request", "never"] | None,
        typer.Option(
            "--approval",
            help="Approval policy forwarded to Codex.",
            case_sensitive=True,
        ),
    ] = None,
    dangerous: Annotated[
        bool,
        typer.Option("--dangerous", help="Forward --dangerously-bypass-approvals-and-sandbox to Codex."),
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
    search: Annotated[bool, typer.Option("--search", help="Enable Codex web search tool.")] = False,
) -> None:
    resolved = _resolve_runtime_config_or_exit(
        repo_hint=repo,
        overrides={
            "repo": repo,
            "model": model,
            "sandbox": sandbox,
            "approval": approval,
            "app_mcp_name": app_mcp_name,
            "app_mcp_url": app_mcp_url,
            "app_mcp_bearer_env": app_mcp_bearer_env,
            "system_prompt_file": system_prompt_file,
        },
    )

    exit_code = _run_codex(
        command="chat",
        prompt=prompt,
        passthrough=_normalize_passthrough(ctx),
        repo=str(resolved.values["repo"]),
        model=str(resolved.values["model"]),
        sandbox=str(resolved.values["sandbox"]),
        approval=str(resolved.values["approval"]),
        dangerous=dangerous,
        app_mcp_name=str(resolved.values["app_mcp_name"]),
        app_mcp_url=str(resolved.values["app_mcp_url"]),
        app_mcp_bearer_env=str(resolved.values["app_mcp_bearer_env"]),
        system_prompt_file=str(resolved.values["system_prompt_file"]),
        no_app_mcp=no_app_mcp,
        search=search,
        json_output=False,
        skip_git_repo_check=False,
    )
    raise typer.Exit(code=exit_code)


@app.command(
    "exec",
    context_settings=CHAT_EXEC_CONTEXT_SETTINGS,
    help="Run non-interactive ConstructOS CLI execution backed by Codex.",
)
def exec_command(
    ctx: typer.Context,
    prompt: Annotated[str, typer.Argument(help="Prompt for Codex exec. Use '-' to read from stdin.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", "-C", help="Repository directory passed to Codex with --cd.")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="Codex model (passed as -m).")] = None,
    sandbox: Annotated[
        Literal["read-only", "workspace-write", "danger-full-access"] | None,
        typer.Option(
            "--sandbox",
            help="Sandbox policy forwarded to Codex.",
            case_sensitive=True,
        ),
    ] = None,
    approval: Annotated[
        Literal["untrusted", "on-request", "never"] | None,
        typer.Option(
            "--approval",
            help="Approval policy forwarded to Codex.",
            case_sensitive=True,
        ),
    ] = None,
    dangerous: Annotated[
        bool,
        typer.Option("--dangerous", help="Forward --dangerously-bypass-approvals-and-sandbox to Codex."),
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
    json_output: Annotated[bool, typer.Option("--json", help="Forward --json to codex exec output.")] = False,
    skip_git_repo_check: Annotated[
        bool,
        typer.Option("--skip-git-repo-check", help="Forward --skip-git-repo-check to codex exec."),
    ] = False,
) -> None:
    resolved = _resolve_runtime_config_or_exit(
        repo_hint=repo,
        overrides={
            "repo": repo,
            "model": model,
            "sandbox": sandbox,
            "approval": approval,
            "app_mcp_name": app_mcp_name,
            "app_mcp_url": app_mcp_url,
            "app_mcp_bearer_env": app_mcp_bearer_env,
            "system_prompt_file": system_prompt_file,
        },
    )

    exit_code = _run_codex(
        command="exec",
        prompt=prompt,
        passthrough=_normalize_passthrough(ctx),
        repo=str(resolved.values["repo"]),
        model=str(resolved.values["model"]),
        sandbox=str(resolved.values["sandbox"]),
        approval=str(resolved.values["approval"]),
        dangerous=dangerous,
        app_mcp_name=str(resolved.values["app_mcp_name"]),
        app_mcp_url=str(resolved.values["app_mcp_url"]),
        app_mcp_bearer_env=str(resolved.values["app_mcp_bearer_env"]),
        system_prompt_file=str(resolved.values["system_prompt_file"]),
        no_app_mcp=no_app_mcp,
        search=False,
        json_output=json_output,
        skip_git_repo_check=skip_git_repo_check,
    )
    raise typer.Exit(code=exit_code)


@app.command(
    "doctor",
    help="Run ConstructOS CLI diagnostics for Codex and ConstructOS MCP connectivity.",
)
def doctor_command(
    repo: Annotated[str | None, typer.Option("--repo", "-C", help="Repository path used to resolve local .cos/config.toml.")] = None,
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
            "app_mcp_url": app_mcp_url,
            "app_mcp_bearer_env": app_mcp_bearer_env,
            "system_prompt_file": system_prompt_file,
        },
    )
    args = SimpleNamespace(
        app_mcp_url=str(resolved.values["app_mcp_url"]),
        app_mcp_bearer_env=str(resolved.values["app_mcp_bearer_env"]),
        system_prompt_file=str(resolved.values["system_prompt_file"]),
        timeout_seconds=timeout_seconds,
        json=json_output,
    )
    exit_code = run_doctor(args)
    raise typer.Exit(code=exit_code)
