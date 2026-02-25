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
                detail = (proc.stderr or proc.stdout or "").strip()
                checks.append(
                    {
                        "name": "codex_version",
                        "status": "fail",
                        "message": f"codex --version failed (exit={proc.returncode}): {detail[:300]}",
                    }
                )
        except Exception as exc:
            checks.append({"name": "codex_version", "status": "fail", "message": f"codex --version error: {exc}"})
    else:
        checks.append({"name": "codex_path", "status": "fail", "message": "codex binary not found in PATH"})

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
        tcp_ok, tcp_message = tcp_probe(host, port, float(args.timeout_seconds))
        checks.append({"name": "mcp_tcp", "status": "ok" if tcp_ok else "fail", "message": tcp_message})
        if tcp_ok:
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
