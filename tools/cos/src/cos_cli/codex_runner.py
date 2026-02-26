from __future__ import annotations

import argparse
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


def require_codex_binary() -> str:
    codex_path = shutil.which("codex")
    if codex_path:
        return codex_path
    raise RuntimeError(
        "The `codex` binary is not available in PATH. "
        "Install Codex first, then run `cos` again."
    )


def _trim_process_detail(proc: subprocess.CompletedProcess[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    if not detail:
        return "no output"
    return detail[:300]


def require_codex_runtime(args: argparse.Namespace) -> None:
    backend = str(getattr(args, "codex_backend", "local") or "").strip().lower()
    if backend == "local":
        require_codex_binary()
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

    codex_binary = str(getattr(args, "docker_codex_binary", "codex") or "").strip() or "codex"
    check_proc = subprocess.run(
        ["docker", "exec", container, codex_binary, "--version"],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    if check_proc.returncode != 0:
        raise RuntimeError(
            f"Codex binary {codex_binary!r} was not found in Docker container {container!r}."
        )


def find_docker_resume_home(*, container: str, session_id: str, search_root: str) -> str:
    sid = str(session_id or "").strip()
    if not sid or not SESSION_ID_PATTERN.fullmatch(sid):
        return ""
    root = str(search_root or "").strip()
    if not root:
        return ""

    code = (
        "from pathlib import Path\n"
        "import sys\n"
        "sid = sys.argv[1]\n"
        "root = Path(sys.argv[2])\n"
        "if not root.exists():\n"
        "    raise SystemExit(0)\n"
        "marker = '/.codex/sessions/'\n"
        "for path in root.rglob(f'*{sid}.jsonl'):\n"
        "    text = str(path)\n"
        "    idx = text.find(marker)\n"
        "    if idx != -1:\n"
        "        print(text[:idx])\n"
        "        raise SystemExit(0)\n"
    )
    proc = subprocess.run(
        ["docker", "exec", container, "python", "-c", code, sid, root],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to search docker Codex sessions for {sid!r}: {_trim_process_detail(proc)}"
        )
    return str(proc.stdout or "").strip()


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

    docker_workdir = str(getattr(args, "docker_workdir", "") or "").strip()
    if docker_workdir:
        docker_cmd.extend(["-w", docker_workdir])

    docker_cmd.append(container)
    docker_cmd.extend(cmd)
    return docker_cmd


def build_codex_command(args: argparse.Namespace, user_prompt: str, passthrough: list[str]) -> list[str]:
    cmd = _build_inner_codex_command(args=args, user_prompt=user_prompt, passthrough=passthrough)
    backend = str(getattr(args, "codex_backend", "local") or "").strip().lower()
    if backend == "local":
        return cmd
    if backend == "docker":
        return _wrap_with_docker_exec(args=args, cmd=cmd)
    raise RuntimeError("Unsupported codex backend. Allowed: local, docker.")
