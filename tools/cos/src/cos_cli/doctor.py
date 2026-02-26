from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request


def resolve_mcp_endpoint(url: str) -> tuple[str, str, int]:
    parsed = url_parse.urlparse(str(url or "").strip())
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise ValueError("MCP URL must use http or https")
    host = str(parsed.hostname or "").strip()
    if not host:
        raise ValueError("MCP URL must include a host")
    port = int(parsed.port or (443 if scheme == "https" else 80))
    return scheme, host, port


def tcp_probe(host: str, port: int, timeout_seconds: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=max(0.2, float(timeout_seconds))):
            return True, f"Connected to {host}:{port}."
    except OSError as exc:
        return False, f"Cannot connect to {host}:{port}: {exc}"


def http_probe(url: str, timeout_seconds: float) -> tuple[bool, str]:
    req = url_request.Request(url, method="GET")
    try:
        with url_request.urlopen(req, timeout=max(0.2, float(timeout_seconds))) as resp:
            return True, f"HTTP probe status: {int(resp.status)}"
    except url_error.HTTPError as exc:
        return True, f"HTTP probe status: {int(exc.code)}"
    except url_error.URLError as exc:
        return False, f"HTTP probe failed: {exc.reason}"
    except OSError as exc:
        return False, f"HTTP probe failed: {exc}"


def _trim_process_detail(proc: subprocess.CompletedProcess[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    if detail:
        return detail[:300]
    return f"exit={proc.returncode}"


def _collect_local_codex_checks(checks: list[dict[str, str]]) -> None:
    codex_path = shutil.which("codex")
    if codex_path:
        checks.append({"name": "codex_path", "status": "ok", "message": f"Found at {codex_path}"})
        try:
            proc = subprocess.run(
                ["codex", "--version"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                version_text = (proc.stdout or proc.stderr or "").strip().splitlines()
                version_line = version_text[0] if version_text else "codex --version ok"
                checks.append({"name": "codex_version", "status": "ok", "message": version_line})
            else:
                checks.append(
                    {
                        "name": "codex_version",
                        "status": "fail",
                        "message": f"codex --version failed: {_trim_process_detail(proc)}",
                    }
                )
        except Exception as exc:
            checks.append({"name": "codex_version", "status": "fail", "message": f"codex --version error: {exc}"})
    else:
        checks.append({"name": "codex_path", "status": "fail", "message": "codex binary not found in PATH"})


def _collect_docker_codex_checks(checks: list[dict[str, str]], args: argparse.Namespace) -> None:
    docker_path = shutil.which("docker")
    if not docker_path:
        checks.append({"name": "docker_path", "status": "fail", "message": "docker binary not found in PATH"})
        return
    checks.append({"name": "docker_path", "status": "ok", "message": f"Found at {docker_path}"})

    container = str(args.docker_container or "").strip()
    if not container:
        checks.append({"name": "docker_container", "status": "fail", "message": "Container name is empty."})
        return

    inspect_proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    if inspect_proc.returncode != 0:
        checks.append(
            {
                "name": "docker_container",
                "status": "fail",
                "message": f"Container {container!r} unavailable: {_trim_process_detail(inspect_proc)}",
            }
        )
        return
    if str(inspect_proc.stdout or "").strip().lower() != "true":
        checks.append(
            {
                "name": "docker_container",
                "status": "fail",
                "message": f"Container {container!r} is not running.",
            }
        )
        return
    checks.append({"name": "docker_container", "status": "ok", "message": f"Container {container!r} is running."})

    codex_binary = str(args.docker_codex_binary or "codex").strip() or "codex"
    codex_proc = subprocess.run(
        ["docker", "exec", container, codex_binary, "--version"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if codex_proc.returncode == 0:
        version_text = (codex_proc.stdout or codex_proc.stderr or "").strip().splitlines()
        version_line = version_text[0] if version_text else f"{codex_binary} --version ok"
        checks.append({"name": "codex_in_docker", "status": "ok", "message": version_line})
    else:
        checks.append(
            {
                "name": "codex_in_docker",
                "status": "fail",
                "message": (
                    f"Failed to run {codex_binary!r} in container {container!r}: "
                    f"{_trim_process_detail(codex_proc)}"
                ),
            }
        )
    _collect_docker_git_auth_checks(checks, container=container)


def _collect_docker_git_auth_checks(checks: list[dict[str, str]], *, container: str) -> None:
    git_proc = subprocess.run(
        ["docker", "exec", container, "git", "--version"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if git_proc.returncode == 0:
        version_text = (git_proc.stdout or git_proc.stderr or "").strip().splitlines()
        version_line = version_text[0] if version_text else "git --version ok"
        checks.append({"name": "git_in_docker", "status": "ok", "message": version_line})
    else:
        checks.append(
            {
                "name": "git_in_docker",
                "status": "fail",
                "message": (
                    f"Failed to run 'git --version' in container {container!r}: "
                    f"{_trim_process_detail(git_proc)}"
                ),
            }
        )
        return

    pat_proc = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-lc",
            "if [ -n \"${GITHUB_PAT:-}\" ]; then echo set; else echo missing; fi",
        ],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    if pat_proc.returncode != 0:
        checks.append(
            {
                "name": "github_pat_in_docker",
                "status": "warn",
                "message": (
                    f"Could not verify GITHUB_PAT in container {container!r}: "
                    f"{_trim_process_detail(pat_proc)}"
                ),
            }
        )
        checks.append(
            {
                "name": "git_push_auth_in_docker",
                "status": "warn",
                "message": "Skipped askpass verification because GITHUB_PAT availability could not be determined.",
            }
        )
        return

    pat_is_set = str(pat_proc.stdout or "").strip().lower() == "set"
    if pat_is_set:
        checks.append(
            {
                "name": "github_pat_in_docker",
                "status": "ok",
                "message": "Environment variable GITHUB_PAT is set in container.",
            }
        )
    else:
        checks.append(
            {
                "name": "github_pat_in_docker",
                "status": "warn",
                "message": "Environment variable GITHUB_PAT is not set in container.",
            }
        )
        checks.append(
            {
                "name": "git_push_auth_in_docker",
                "status": "warn",
                "message": "Skipped askpass verification because GITHUB_PAT is not set.",
            }
        )
        return

    askpass_proc = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-lc",
            'p="${HOME:-/home/app}/.codex/git-askpass.sh"; if [ -x "$p" ]; then echo "$p"; fi',
        ],
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )
    if askpass_proc.returncode != 0:
        checks.append(
            {
                "name": "git_push_auth_in_docker",
                "status": "fail",
                "message": (
                    f"Failed to verify git askpass script in container {container!r}: "
                    f"{_trim_process_detail(askpass_proc)}"
                ),
            }
        )
        return

    askpass_path = str(askpass_proc.stdout or "").strip()
    if askpass_path:
        checks.append(
            {
                "name": "git_push_auth_in_docker",
                "status": "ok",
                "message": f"Found executable git askpass script at {askpass_path}",
            }
        )
    else:
        checks.append(
            {
                "name": "git_push_auth_in_docker",
                "status": "fail",
                "message": "GITHUB_PAT is set but git askpass script is missing or not executable.",
            }
        )


def docker_tcp_probe(container: str, host: str, port: int, timeout_seconds: float) -> tuple[bool, str]:
    code = (
        "import socket,sys\n"
        "host=sys.argv[1]\n"
        "port=int(sys.argv[2])\n"
        "timeout=max(0.2,float(sys.argv[3]))\n"
        "socket.create_connection((host,port),timeout=timeout).close()\n"
        "print(f'Connected to {host}:{port} from container.')\n"
    )
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "python", "-c", code, host, str(port), str(timeout_seconds)],
            text=True,
            capture_output=True,
            timeout=12,
            check=False,
        )
    except FileNotFoundError:
        return False, "Cannot connect from container because 'docker' is not available in PATH."
    except OSError as exc:
        return False, f"Cannot connect to {host}:{port} from container: {exc}"
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip() or f"Connected to {host}:{port} from container."
    return False, f"Cannot connect to {host}:{port} from container: {_trim_process_detail(proc)}"


def docker_http_probe(container: str, url: str, timeout_seconds: float) -> tuple[bool, str]:
    code = (
        "from urllib import request,error\n"
        "import sys\n"
        "url=sys.argv[1]\n"
        "timeout=max(0.2,float(sys.argv[2]))\n"
        "req=request.Request(url,method='GET')\n"
        "try:\n"
        "    with request.urlopen(req,timeout=timeout) as resp:\n"
        "        print(f'HTTP probe status: {int(resp.status)}')\n"
        "except error.HTTPError as exc:\n"
        "    print(f'HTTP probe status: {int(exc.code)}')\n"
        "except Exception as exc:\n"
        "    print(f'HTTP probe failed: {exc}')\n"
        "    raise SystemExit(2)\n"
    )
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "python", "-c", code, url, str(timeout_seconds)],
            text=True,
            capture_output=True,
            timeout=12,
            check=False,
        )
    except FileNotFoundError:
        return False, "HTTP probe from container failed because 'docker' is not available in PATH."
    except OSError as exc:
        return False, f"HTTP probe failed from container: {exc}"
    output = (proc.stdout or "").strip()
    if proc.returncode == 0:
        return True, output or "HTTP probe succeeded from container."
    if output:
        return False, output[:300]
    return False, f"HTTP probe failed from container: {_trim_process_detail(proc)}"


def collect_doctor_checks(args: argparse.Namespace) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    python_version = sys.version.split()[0]
    checks.append(
        {
            "name": "python",
            "status": "ok",
            "message": f"Python {python_version}",
        }
    )

    backend = str(getattr(args, "codex_backend", "local") or "").strip().lower()
    if backend not in {"local", "docker"}:
        checks.append(
            {
                "name": "codex_backend",
                "status": "fail",
                "message": f"Unsupported backend {backend!r}. Allowed: local, docker.",
            }
        )
    else:
        checks.append({"name": "codex_backend", "status": "ok", "message": f"Using backend {backend!r}."})
        if backend == "docker":
            _collect_docker_codex_checks(checks, args)
        else:
            _collect_local_codex_checks(checks)

    mcp_url = str(args.app_mcp_url or "").strip()
    try:
        scheme, host, port = resolve_mcp_endpoint(mcp_url)
        checks.append(
            {
                "name": "mcp_url",
                "status": "ok",
                "message": f"Parsed {scheme} endpoint {host}:{port}",
            }
        )
        if backend == "docker":
            container = str(getattr(args, "docker_container", "") or "").strip()
            tcp_ok, tcp_message = docker_tcp_probe(container, host, port, float(args.timeout_seconds))
        else:
            tcp_ok, tcp_message = tcp_probe(host, port, float(args.timeout_seconds))
        checks.append({"name": "mcp_tcp", "status": "ok" if tcp_ok else "fail", "message": tcp_message})
        if tcp_ok:
            if backend == "docker":
                container = str(getattr(args, "docker_container", "") or "").strip()
                http_ok, http_message = docker_http_probe(container, mcp_url, float(args.timeout_seconds))
            else:
                http_ok, http_message = http_probe(mcp_url, float(args.timeout_seconds))
            checks.append({"name": "mcp_http", "status": "ok" if http_ok else "warn", "message": http_message})
    except ValueError as exc:
        checks.append({"name": "mcp_url", "status": "fail", "message": str(exc)})

    system_prompt_path = Path(str(args.system_prompt_file or "")).expanduser()
    if system_prompt_path.exists() and system_prompt_path.is_file():
        checks.append(
            {
                "name": "system_prompt_file",
                "status": "ok",
                "message": f"Found {system_prompt_path}",
            }
        )
    else:
        checks.append(
            {
                "name": "system_prompt_file",
                "status": "warn",
                "message": f"Optional file not found: {system_prompt_path}",
            }
        )

    token_env = str(args.app_mcp_bearer_env or "").strip()
    if token_env:
        if str(os.getenv(token_env, "")).strip():
            checks.append(
                {
                    "name": "mcp_bearer_env",
                    "status": "ok",
                    "message": f"Environment variable '{token_env}' is set.",
                }
            )
        else:
            checks.append(
                {
                    "name": "mcp_bearer_env",
                    "status": "warn",
                    "message": f"Environment variable '{token_env}' is not set.",
                }
            )

    return checks


def summarize_check_counts(checks: list[dict[str, str]]) -> dict[str, int]:
    summary = {"ok": 0, "warn": 0, "fail": 0}
    for item in checks:
        status = str(item.get("status") or "").strip().lower()
        if status in summary:
            summary[status] += 1
    return summary


def print_doctor_human(checks: list[dict[str, str]], summary: dict[str, int]) -> None:
    print("COS doctor")
    print("")
    for item in checks:
        status = str(item.get("status") or "").strip().lower()
        symbol = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(status, "INFO")
        name = str(item.get("name") or "").strip()
        message = str(item.get("message") or "").strip()
        print(f"- [{symbol}] {name}: {message}")
    print("")
    print(f"Summary: ok={summary['ok']} warn={summary['warn']} fail={summary['fail']}")


def run_doctor(args: argparse.Namespace) -> int:
    checks = collect_doctor_checks(args)
    summary = summarize_check_counts(checks)
    if bool(args.json):
        print(json.dumps({"checks": checks, "summary": summary}, ensure_ascii=True))
    else:
        print_doctor_human(checks, summary)
    return 1 if summary["fail"] > 0 else 0
