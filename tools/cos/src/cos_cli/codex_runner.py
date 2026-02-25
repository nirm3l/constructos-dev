from __future__ import annotations

import argparse
import shutil


def toml_quote(value: str) -> str:
    escaped = (
        str(value or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def require_codex_binary() -> str:
    codex_path = shutil.which("codex")
    if codex_path:
        return codex_path
    raise RuntimeError(
        "The `codex` binary is not available in PATH. "
        "Install Codex first, then run `cos` again."
    )


def build_codex_command(args: argparse.Namespace, user_prompt: str, passthrough: list[str]) -> list[str]:
    if args.command == "chat":
        cmd: list[str] = ["codex"]
    elif args.command == "exec":
        cmd = ["codex", "exec"]
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")

    repo = str(args.repo or "").strip()
    if repo:
        cmd.extend(["--cd", repo])

    model = str(args.model or "").strip()
    if model:
        cmd.extend(["-m", model])

    cmd.extend(["--sandbox", args.sandbox])
    cmd.extend(["--ask-for-approval", args.approval])

    if args.dangerous:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")

    if args.command == "chat" and bool(args.search):
        cmd.append("--search")

    if args.command == "exec":
        if bool(args.json):
            cmd.append("--json")
        if bool(args.skip_git_repo_check):
            cmd.append("--skip-git-repo-check")

    if not bool(args.no_app_mcp):
        mcp_name = str(args.app_mcp_name or "").strip()
        mcp_url = str(args.app_mcp_url or "").strip()
        if mcp_name and mcp_url:
            cmd.extend(
                [
                    "-c",
                    f'mcp_servers.{toml_quote(mcp_name)}.url={toml_quote(mcp_url)}',
                    "-c",
                    f"mcp_servers.{toml_quote(mcp_name)}.enabled=true",
                ]
            )
            token_env = str(args.app_mcp_bearer_env or "").strip()
            if token_env:
                cmd.extend(
                    [
                        "-c",
                        (
                            f"mcp_servers.{toml_quote(mcp_name)}."
                            f"bearer_token_env_var={toml_quote(token_env)}"
                        ),
                    ]
                )

    if passthrough:
        cmd.extend(passthrough)

    cmd.append(user_prompt)
    return cmd
