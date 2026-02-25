from __future__ import annotations

import typer

from cos_cli.parser import app


def main(argv: list[str] | None = None) -> int:
    try:
        result = app(args=argv, prog_name="cos", standalone_mode=False)
        if isinstance(result, int):
            return int(result)
        return 0
    except typer.Exit as exc:
        return int(exc.exit_code)
    except Exception as exc:  # pragma: no cover - defensive error mapping for CLI runtime.
        show = getattr(exc, "show", None)
        if callable(show):
            show()
            return int(getattr(exc, "exit_code", 1))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
