#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pty
import re
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
URL_RE = re.compile(r"https?://\S+")


def strip_ansi(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive Claude CLI through onboarding and Console login until an OAuth URL is emitted."
    )
    parser.add_argument(
        "--login-method",
        choices=("console", "claudeai"),
        default="console",
        help="Claude login method to select once the login menu appears.",
    )
    parser.add_argument(
        "--home",
        default="",
        help="Optional HOME directory to use for the Claude session. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=45.0,
        help="Maximum number of seconds to wait for the OAuth URL.",
    )
    parser.add_argument(
        "--exit-after-url",
        action="store_true",
        help="Exit immediately after printing the OAuth URL instead of keeping the Claude process alive.",
    )
    parser.add_argument(
        "--debug-output",
        action="store_true",
        help="Echo sanitized Claude terminal output while the harness runs.",
    )
    return parser


def normalize_plain_text(value: str) -> str:
    return strip_ansi(value).replace("\r", "\n")


def run_harness(*, login_method: str, home_dir: Path, timeout_seconds: float, exit_after_url: bool, debug_output: bool) -> int:
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / ".claude").mkdir(parents=True, exist_ok=True)

    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        ["claude"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env={
            **os.environ,
            "HOME": str(home_dir),
            "TERM": str(os.environ.get("TERM") or "xterm-256color"),
        },
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave_fd)

    buf = ""
    url: str | None = None
    stage = "boot"
    last_action_at = 0.0
    started_at = time.time()

    try:
        while time.time() - started_at < timeout_seconds:
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096).decode("utf-8", errors="ignore")
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                plain = normalize_plain_text(buf)

                if debug_output:
                    sys.stdout.write(strip_ansi(chunk))
                    sys.stdout.flush()

                now = time.time()

                if stage == "boot" and (
                    "Choose the text style" in plain
                    or "Choosethetextstylethatlooksbestwithyourterminal" in plain
                ):
                    os.write(master_fd, b"\r")
                    stage = "theme"
                    last_action_at = now
                    if debug_output:
                        print("\n[SENT theme enter]", flush=True)

                if stage == "theme" and now - last_action_at > 0.5 and (
                    "Syntax theme:" in plain
                    or "Syntaxhighlightingavailableonlyinnativebuild" in plain
                ):
                    os.write(master_fd, b"/login\r")
                    stage = "login"
                    last_action_at = now
                    if debug_output:
                        print("\n[SENT /login]", flush=True)

                if stage == "login" and now - last_action_at > 0.5 and (
                    "Select login method" in plain
                    or "Selectloginmethod" in plain
                ):
                    if login_method == "console":
                        os.write(master_fd, b"\x1b[B\r")
                    else:
                        os.write(master_fd, b"\r")
                    stage = "choice"
                    last_action_at = now
                    if debug_output:
                        print("\n[SENT login method choice]", flush=True)

                match = URL_RE.search(plain)
                if match:
                    url = match.group(0)
                    print(url, flush=True)
                    if exit_after_url:
                        return 0
                    break

            if process.poll() is not None:
                break

        if url is None:
            tail = normalize_plain_text(buf)[-2000:].strip()
            if tail:
                print(tail, file=sys.stderr)
            return 1

        while process.poll() is None:
            time.sleep(0.2)
        return 0 if process.returncode == 0 else int(process.returncode or 1)
    finally:
        try:
            os.close(master_fd)
        except Exception:
            pass
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    home_dir = Path(args.home).expanduser() if args.home else Path(tempfile.mkdtemp(prefix="claude-console-login-"))
    return run_harness(
        login_method=args.login_method,
        home_dir=home_dir,
        timeout_seconds=float(args.timeout_seconds),
        exit_after_url=bool(args.exit_after_url),
        debug_output=bool(args.debug_output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
