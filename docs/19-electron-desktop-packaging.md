# 19 Electron Desktop Packaging

## Goal
Provide a desktop entry point for ConstructOS on macOS, Windows, and Ubuntu without changing backend architecture.

## Approach
Use an Electron shell that loads the existing app URL (default `http://127.0.0.1:8080`), which keeps:
- same-origin API calls (`/api/...`),
- cookie-based auth sessions,
- SSE realtime stream behavior.

This avoids frontend rewrites and keeps the same backend contract.

## Why not frontend-only packaging
The current frontend depends on backend-served origin paths and auth/session behavior:
- `/api/*` calls with `credentials: "same-origin"`,
- EventSource stream from `/api/notifications/stream`,
- Vite production base `/static/`,
- backend root route serving `index.html`.

A standalone file-based frontend bundle would break these assumptions.

## Implementation in this repository
- Desktop project path: `desktop/`
- Main process: `desktop/main.cjs`
- Secure preload bridge: `desktop/preload.cjs`
- Local status pages:
  - `desktop/renderer/loading.html`
  - `desktop/renderer/offline.html`
- Packaging config: `desktop/package.json` (`electron-builder`)
- Linux launcher wrapper (sandbox precheck): `desktop/scripts/run-electron.cjs`
- Optional mac notarization hook: `desktop/scripts/notarize.cjs`
- Build resources/icons folder: `desktop/build/`

## Runtime behavior
1. Electron starts and resolves app/health URLs.
2. It polls health endpoint until timeout.
3. If healthy, it loads app URL in the desktop window.
4. If not healthy, it shows an offline page with Retry/Open Browser/Quit actions.
5. On Linux, startup checks Electron sandbox permissions and prints fix instructions if setuid sandbox is not configured.
6. Endpoint can be changed from desktop UI and persisted in user data.

## Endpoint configuration UI
- Menu: `File -> Connection Settings` (`Cmd/Ctrl + ,`)
- Offline screen: inline endpoint editor (`Save Endpoint + Retry`)

Saved config fields:
- `appUrl`
- `healthUrl`
- `startupTimeoutMs`
- `retryIntervalMs`

## Packaging targets
- macOS: `dmg`, `zip`
- Windows: `nsis`, `zip`
- Linux: `AppImage`, `deb`, `tar.gz`

## Build commands
```bash
cd desktop
npm install
npm run dist
```

Per-platform commands:
- `npm run dist:mac`
- `npm run dist:win`
- `npm run dist:linux`

Artifacts output directory: `desktop/release/`

## CI automation
Workflow:
- `.github/workflows/desktop-artifacts.yml`

Behavior:
- Manual `workflow_dispatch` build (no automatic triggers on branch pushes).
- Uploads artifacts for each OS matrix target.
- When `release_tag` input is provided (for example `desktop-v0.1.3`), publishes assets to `nirm3l/constructos` GitHub Releases.

Optional signing/notarization secrets:
- `DESKTOP_CSC_LINK`
- `DESKTOP_CSC_KEY_PASSWORD`
- `DESKTOP_CSC_NAME`
- `DESKTOP_WIN_CSC_LINK`
- `DESKTOP_WIN_CSC_KEY_PASSWORD`
- `DESKTOP_APPLE_ID`
- `DESKTOP_APPLE_APP_SPECIFIC_PASSWORD`
- `DESKTOP_APPLE_TEAM_ID`
- `CONSTRUCTOS_RELEASE_TOKEN` (required for cross-repo publish to `nirm3l/constructos`)

Helper script (sets any provided env var via `gh secret set`):
```bash
DESKTOP_CSC_LINK=... \
DESKTOP_CSC_KEY_PASSWORD=... \
DESKTOP_APPLE_ID=... \
DESKTOP_APPLE_APP_SPECIFIC_PASSWORD=... \
DESKTOP_APPLE_TEAM_ID=... \
./scripts/set_desktop_signing_secrets.sh
```

## Operational guidance
- Keep backend deployment unchanged (`constructos-app` compose project).
- Desktop app should be treated as a shell/launcher, not as backend replacement.
- For customer-facing installers, add code signing/notarization in CI for each OS.
