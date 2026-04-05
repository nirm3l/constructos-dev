from __future__ import annotations

from typing import Final

THEME_CONSTRUCTOS_LIGHT: Final[str] = "constructos-light"
THEME_CONSTRUCTOS_NIGHT: Final[str] = "constructos-night"
THEME_SYMPHONY_LIGHT: Final[str] = "symphony-light"
THEME_SYMPHONY_NIGHT: Final[str] = "symphony-night"

DEFAULT_THEME: Final[str] = THEME_SYMPHONY_LIGHT

VALID_THEMES: Final[frozenset[str]] = frozenset(
    {
        THEME_CONSTRUCTOS_LIGHT,
        THEME_CONSTRUCTOS_NIGHT,
        THEME_SYMPHONY_LIGHT,
        THEME_SYMPHONY_NIGHT,
    }
)

LEGACY_THEME_ALIASES: Final[dict[str, str]] = {
    "light": THEME_CONSTRUCTOS_LIGHT,
    "dark": THEME_CONSTRUCTOS_NIGHT,
}


def normalize_theme(value: object, *, default: str = DEFAULT_THEME) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_THEMES:
        return normalized
    if normalized in LEGACY_THEME_ALIASES:
        return LEGACY_THEME_ALIASES[normalized]
    return default


def theme_mode(theme: object) -> str:
    normalized = normalize_theme(theme)
    return "dark" if normalized.endswith("-night") else "light"


def toggle_theme(theme: object) -> str:
    normalized = normalize_theme(theme)
    if normalized.startswith("symphony-"):
        return THEME_SYMPHONY_LIGHT if normalized.endswith("-night") else THEME_SYMPHONY_NIGHT
    return THEME_CONSTRUCTOS_LIGHT if normalized.endswith("-night") else THEME_CONSTRUCTOS_NIGHT
