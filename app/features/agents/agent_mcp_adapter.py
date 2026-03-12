from __future__ import annotations

import sys

from .codex_mcp_adapter import (
    EMPTY_ASSISTANT_SUMMARY,
    main as _legacy_main,
    run_agent_home_cleanup_if_due,
    run_codex_home_cleanup_if_due,
    run_structured_agent_prompt,
    run_structured_agent_prompt_with_usage,
    run_structured_codex_prompt,
    run_structured_codex_prompt_with_usage,
)


def main() -> int:
    return _legacy_main()


__all__ = [
    "EMPTY_ASSISTANT_SUMMARY",
    "main",
    "run_agent_home_cleanup_if_due",
    "run_codex_home_cleanup_if_due",
    "run_structured_agent_prompt",
    "run_structured_agent_prompt_with_usage",
    "run_structured_codex_prompt",
    "run_structured_codex_prompt_with_usage",
]


if __name__ == "__main__":
    raise SystemExit(main())
