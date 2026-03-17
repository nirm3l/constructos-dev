from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess


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


MCP_SERVER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_mcp_server_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return value
    if not MCP_SERVER_NAME_PATTERN.fullmatch(value):
        raise RuntimeError(
            f"Invalid MCP server name {value!r}: must match pattern ^[a-zA-Z0-9_-]+$"
        )
    return value


def _stable_json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _provider_name(args: argparse.Namespace) -> str:
    return str(getattr(args, "provider", "codex") or "").strip().lower() or "codex"


def _provider_binary_name(provider: str) -> str:
    return "claude" if provider == "claude" else "codex"


def _provider_binary_attr(provider: str) -> str:
    return "docker_claude_binary" if provider == "claude" else "docker_codex_binary"


def _provider_session_marker(provider: str) -> str:
    return "/.claude/projects/" if provider == "claude" else "/.codex/sessions/"


def _provider_runtime_home(provider: str) -> str:
    if provider == "claude":
        return "/home/app/agent-home/cos/shared-claude-home"
    return "/home/app/agent-home/cos/shared-codex-home"


def require_provider_binary(provider: str) -> str:
    binary_name = _provider_binary_name(provider)
    binary_path = shutil.which(binary_name)
    if binary_path:
        return binary_path
    raise RuntimeError(
        f"The `{binary_name}` binary is not available in PATH. "
        f"Install {binary_name} first, then run `cos` again."
    )


def _trim_process_detail(proc: subprocess.CompletedProcess[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    if not detail:
        return "no output"
    return detail[:300]


def require_codex_runtime(args: argparse.Namespace) -> None:
    backend = str(getattr(args, "codex_backend", "local") or "").strip().lower()
    provider = _provider_name(args)
    if backend == "local":
        require_provider_binary(provider)
        return

    if backend != "docker":
        raise RuntimeError("Unsupported codex backend. Allowed: local, docker.")

    docker_path = shutil.which("docker")
    if not docker_path:
        raise RuntimeError(
            "The `docker` binary is not available in PATH. "
            "Install Docker first, then run `cos` again."
        )

    container = str(getattr(args, "docker_container", "") or "").strip()
    if not container:
        raise RuntimeError("Docker backend requires a non-empty docker container name.")

    inspect_proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    if inspect_proc.returncode != 0:
        raise RuntimeError(
            f"Docker container {container!r} is not available: {_trim_process_detail(inspect_proc)}"
        )
    if str(inspect_proc.stdout or "").strip().lower() != "true":
        raise RuntimeError(f"Docker container {container!r} is not running.")

    binary_attr = _provider_binary_attr(provider)
    provider_binary = _provider_binary_name(provider)
    docker_binary = str(getattr(args, binary_attr, provider_binary) or "").strip() or provider_binary
    check_proc = subprocess.run(
        ["docker", "exec", container, docker_binary, "--version"],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    if check_proc.returncode != 0:
        raise RuntimeError(
            f"{provider.title()} binary {docker_binary!r} was not found in Docker container {container!r}."
        )


def find_docker_resume_home(*, provider: str, container: str, session_id: str, search_root: str) -> str:
    context = find_docker_resume_context(
        provider=provider,
        container=container,
        session_id=session_id,
        search_root=search_root,
    )
    return str(context.get("home") or "").strip()


def find_docker_resume_context(*, provider: str, container: str, session_id: str, search_root: str) -> dict[str, str]:
    sid = str(session_id or "").strip()
    if not sid or not SESSION_ID_PATTERN.fullmatch(sid):
        return {}
    root = str(search_root or "").strip()
    if not root:
        return {}
    marker = _provider_session_marker(provider)

    code = (
        "from pathlib import Path\n"
        "import json\n"
        "import sys\n"
        "sid = sys.argv[1]\n"
        "root = Path(sys.argv[2])\n"
        "marker = sys.argv[3]\n"
        "if not root.exists():\n"
        "    raise SystemExit(0)\n"
        "for path in root.rglob(f'*{sid}.jsonl'):\n"
        "    text = str(path)\n"
        "    idx = text.find(marker)\n"
        "    if idx != -1:\n"
        "        payload = {'home': text[:idx], 'cwd': ''}\n"
        "        try:\n"
        "            with path.open('r', encoding='utf-8') as handle:\n"
        "                for _ in range(8):\n"
        "                    line = handle.readline()\n"
        "                    if not line:\n"
        "                        break\n"
        "                    item = json.loads(line)\n"
        "                    cwd = str(item.get('cwd') or '').strip()\n"
        "                    if cwd:\n"
        "                        payload['cwd'] = cwd\n"
        "                        break\n"
        "        except Exception:\n"
        "            pass\n"
        "        print(json.dumps(payload, ensure_ascii=True))\n"
        "        raise SystemExit(0)\n"
    )
    proc = subprocess.run(
        ["docker", "exec", container, "python", "-c", code, sid, root, marker],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to search docker {provider.title()} sessions for {sid!r}: {_trim_process_detail(proc)}"
        )
    output = str(proc.stdout or "").strip()
    if not output:
        return {}
    try:
        payload = json.loads(output)
    except Exception:
        return {"home": output, "cwd": ""}
    if not isinstance(payload, dict):
        return {}
    return {
        "home": str(payload.get("home") or "").strip(),
        "cwd": str(payload.get("cwd") or "").strip(),
    }


def ensure_docker_provider_home(*, provider: str, container: str) -> str:
    runtime_home = _provider_runtime_home(provider)
    if provider == "claude":
        source_dir = "/home/app/.claude"
        source_auth = "/home/app/.claude.json"
        inner_dir = ".claude"
        auth_target = ".claude.json"
    else:
        source_dir = "/home/app/.codex"
        source_auth = "/home/app/.codex/auth.json"
        inner_dir = ".codex"
        auth_target = ".codex/auth.json"

    script = f"""
set -euo pipefail
target_home="{runtime_home}"
target_dir="$target_home/{inner_dir}"
mkdir -p "$target_dir"
if [ -f "{source_dir}/config.toml" ] && [ ! -f "$target_dir/config.toml" ]; then
  cp "{source_dir}/config.toml" "$target_dir/config.toml"
fi
if [ -f "{source_auth}" ] && [ ! -f "$target_home/{auth_target}" ]; then
  mkdir -p "$(dirname "$target_home/{auth_target}")"
  cp "{source_auth}" "$target_home/{auth_target}"
fi
printf '%s\\n' "$target_home"
"""
    proc = subprocess.run(
        ["docker", "exec", container, "sh", "-lc", script],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to prepare docker {provider.title()} runtime home: {_trim_process_detail(proc)}"
        )
    return str(proc.stdout or "").strip() or runtime_home


def _claude_permission_mode(args: argparse.Namespace) -> str:
    sandbox = str(getattr(args, "sandbox", "workspace-write") or "").strip().lower()
    approval = str(getattr(args, "approval", "on-request") or "").strip().lower()
    if sandbox == "read-only":
        return "plan"
    if approval == "never":
        return "dontAsk"
    return "default"


def _build_claude_mcp_config(args: argparse.Namespace) -> dict[str, object]:
    mcp_name = validate_mcp_server_name(str(args.app_mcp_name or ""))
    mcp_url = str(args.app_mcp_url or "").strip()
    if not mcp_name or not mcp_url:
        return {}
    server_payload: dict[str, object] = {
        "type": "http",
        "url": mcp_url,
    }
    token_env = str(args.app_mcp_bearer_env or "").strip()
    if token_env:
        server_payload["bearer_token_env_var"] = token_env
    return {"mcpServers": {mcp_name: server_payload}}


def _build_inner_claude_command(args: argparse.Namespace, user_prompt: str, passthrough: list[str]) -> list[str]:
    backend = str(getattr(args, "codex_backend", "local") or "").strip().lower()
    claude_binary = "claude"
    if backend == "docker":
        claude_binary = str(getattr(args, "docker_claude_binary", "claude") or "").strip() or "claude"

    if args.command == "chat":
        cmd: list[str] = [claude_binary]
    elif args.command == "exec":
        cmd = [claude_binary, "--print"]
        if bool(args.json):
            cmd.extend(["--output-format", "json"])
    elif args.command == "resume":
        if bool(getattr(args, "resume_all", False)):
            raise RuntimeError("`cos resume --all` is not supported for provider 'claude'.")
        if bool(getattr(args, "resume_last", False)):
            cmd = [claude_binary, "--continue"]
        else:
            cmd = [claude_binary, "--resume"]
            session_id = str(getattr(args, "resume_session_id", "") or "").strip()
            if session_id:
                cmd.append(session_id)
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")

    model = str(args.model or "").strip()
    if model:
        cmd.extend(["--model", model])

    if args.dangerous:
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd.extend(["--permission-mode", _claude_permission_mode(args)])

    repo = str(args.repo or "").strip()
    if repo:
        cmd.extend(["--add-dir", repo])

    if not bool(args.no_app_mcp):
        payload = _build_claude_mcp_config(args)
        if payload:
            cmd.extend(["--strict-mcp-config", "--mcp-config", _stable_json_dumps(payload)])

    if passthrough:
        cmd.extend(passthrough)

    if str(user_prompt).strip():
        cmd.append("--")
        cmd.append(str(user_prompt).strip())
    return cmd


def _build_inner_codex_command(args: argparse.Namespace, user_prompt: str, passthrough: list[str]) -> list[str]:
    backend = str(getattr(args, "codex_backend", "local") or "").strip().lower()
    codex_binary = "codex"
    if backend == "docker":
        codex_binary = str(getattr(args, "docker_codex_binary", "codex") or "").strip() or "codex"

    if args.command == "chat":
        cmd: list[str] = [codex_binary]
    elif args.command == "exec":
        cmd = [codex_binary, "exec"]
    elif args.command == "resume":
        cmd = [codex_binary, "resume"]
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")

    repo = str(args.repo or "").strip()
    if repo:
        cmd.extend(["--cd", repo])

    model = str(args.model or "").strip()
    if model:
        cmd.extend(["-m", model])

    cmd.extend(["--sandbox", args.sandbox])
    if args.command in {"chat", "resume"}:
        cmd.extend(["--ask-for-approval", args.approval])

    if args.dangerous:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")

    if args.command in {"chat", "resume"} and bool(args.search):
        cmd.append("--search")

    if args.command == "exec":
        if bool(args.json):
            cmd.append("--json")
        if bool(args.skip_git_repo_check):
            cmd.append("--skip-git-repo-check")
    elif args.command == "resume":
        if bool(getattr(args, "resume_last", False)):
            cmd.append("--last")
        if bool(getattr(args, "resume_all", False)):
            cmd.append("--all")
        session_id = str(getattr(args, "resume_session_id", "") or "").strip()
        if session_id:
            cmd.append(session_id)

    if not bool(args.no_app_mcp):
        mcp_name = validate_mcp_server_name(str(args.app_mcp_name or ""))
        mcp_url = str(args.app_mcp_url or "").strip()
        if mcp_name and mcp_url:
            cmd.extend(
                [
                    "-c",
                    f"mcp_servers.{mcp_name}.url={toml_quote(mcp_url)}",
                    "-c",
                    f"mcp_servers.{mcp_name}.enabled=true",
                ]
            )
            token_env = str(args.app_mcp_bearer_env or "").strip()
            if token_env:
                cmd.extend(
                    [
                        "-c",
                        (
                            f"mcp_servers.{mcp_name}."
                            f"bearer_token_env_var={toml_quote(token_env)}"
                        ),
                    ]
                )

    if passthrough:
        cmd.extend(passthrough)

    if str(user_prompt).strip():
        cmd.append(str(user_prompt).strip())
    return cmd


def _effective_docker_workdir(args: argparse.Namespace) -> str:
    provider = _provider_name(args)
    repo = str(getattr(args, "repo", "") or "").strip()
    docker_workdir = str(getattr(args, "docker_workdir", "") or "").strip()
    if provider == "claude" and repo:
        return repo
    return docker_workdir


def _wrap_with_docker_exec(args: argparse.Namespace, cmd: list[str]) -> list[str]:
    container = str(getattr(args, "docker_container", "") or "").strip()
    if not container:
        raise RuntimeError("Docker backend requires a non-empty docker container name.")

    docker_cmd: list[str] = ["docker", "exec", "-i"]
    if args.command in {"chat", "resume"}:
        if not bool(getattr(args, "interactive_tty", False)):
            raise RuntimeError(
                "`cos chat` and `cos resume` in docker backend require an interactive TTY terminal."
            )
        docker_cmd.append("-t")

    docker_home = str(getattr(args, "docker_home", "") or "").strip()
    if docker_home:
        docker_cmd.extend(["-e", f"HOME={docker_home}"])

    docker_workdir = _effective_docker_workdir(args)
    if docker_workdir:
        docker_cmd.extend(["-w", docker_workdir])

    docker_cmd.append(container)
    docker_cmd.extend(cmd)
    return docker_cmd


def build_codex_command(args: argparse.Namespace, user_prompt: str, passthrough: list[str]) -> list[str]:
    provider = _provider_name(args)
    if provider == "claude":
        cmd = _build_inner_claude_command(args=args, user_prompt=user_prompt, passthrough=passthrough)
    else:
        cmd = _build_inner_codex_command(args=args, user_prompt=user_prompt, passthrough=passthrough)

    backend = str(getattr(args, "codex_backend", "local") or "").strip().lower()
    if backend == "local":
        return cmd
    if backend == "docker":
        return _wrap_with_docker_exec(args=args, cmd=cmd)
    raise RuntimeError("Unsupported codex backend. Allowed: local, docker.")
