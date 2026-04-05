export const THEME_KEYS = [
  'constructos-light',
  'constructos-night',
  'symphony-light',
  'symphony-night',
] as const

export type ThemeKey = (typeof THEME_KEYS)[number]
export type ThemeMode = 'light' | 'dark'
export type ThemeBrand = 'constructos' | 'symphony'

export const THEME_LABELS: Record<ThemeKey, string> = {
  'constructos-light': 'ConstructOS light',
  'constructos-night': 'ConstructOS night',
  'symphony-light': 'Symphony light',
  'symphony-night': 'Symphony night',
}

const LEGACY_THEME_ALIASES: Record<string, ThemeKey> = {
  light: 'constructos-light',
  dark: 'constructos-night',
}

const DEFAULT_THEME: ThemeKey = 'symphony-light'

export function normalizeTheme(value: unknown): ThemeKey {
  const normalized = String(value || '').trim().toLowerCase()
  if ((THEME_KEYS as readonly string[]).includes(normalized)) return normalized as ThemeKey
  if (Object.prototype.hasOwnProperty.call(LEGACY_THEME_ALIASES, normalized)) {
    const aliased = LEGACY_THEME_ALIASES[normalized as keyof typeof LEGACY_THEME_ALIASES]
    if (aliased) return aliased
  }
  return DEFAULT_THEME
}

export function getThemeMode(theme: ThemeKey): ThemeMode {
  return theme.endsWith('-night') ? 'dark' : 'light'
}

export function getThemeBrand(theme: ThemeKey): ThemeBrand {
  return theme.startsWith('symphony-') ? 'symphony' : 'constructos'
}

export function toggleTheme(theme: ThemeKey): ThemeKey {
  const brand = getThemeBrand(theme)
  const mode = getThemeMode(theme)
  if (brand === 'symphony') return mode === 'dark' ? 'symphony-light' : 'symphony-night'
  return mode === 'dark' ? 'constructos-light' : 'constructos-night'
}
