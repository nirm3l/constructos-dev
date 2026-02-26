# ConstructOS Desktop (Electron)

This folder contains a cross-platform Electron shell for ConstructOS.

The desktop app does not replace the backend stack. It opens the existing ConstructOS app URL in a desktop window and preserves the same cookie/session behavior used in the browser.

## Runtime model
- `task-app` still serves UI + API on the same origin (default `http://127.0.0.1:8080`).
- Electron waits for `/api/health` before loading the app.
- If backend is unavailable, an offline screen is shown with retry controls.
- Endpoint settings are persisted in Electron user data (`desktop-config.json`).

## Configure endpoint in app
- Open `File -> Connection Settings` (or `Cmd/Ctrl + ,`).
- Update `App URL` and optional `Health URL`.
- Click `Save And Reconnect`.

If backend is offline at startup, you can also edit endpoint values directly on the offline screen and retry.

## Local development

```bash
cd desktop
npm install
npm run start
```

Default target URL:
- `http://127.0.0.1:8080`

Override target URL:

```bash
CONSTRUCTOS_APP_URL="http://127.0.0.1:8080" npm run start
```

Additional optional env vars:
- `CONSTRUCTOS_HEALTH_URL` (default: `${CONSTRUCTOS_APP_URL}/api/health`)
- `CONSTRUCTOS_STARTUP_TIMEOUT_MS` (default: `45000`)
- `CONSTRUCTOS_RETRY_INTERVAL_MS` (default: `1500`)

You can also pass CLI flags:
- `--app-url=http://127.0.0.1:8080`
- `--health-url=http://127.0.0.1:8080/api/health`
- `--startup-timeout-ms=45000`
- `--retry-interval-ms=1500`

Example:

```bash
npm run start -- --app-url=http://127.0.0.1:8080
```

### Linux sandbox note
On some Linux hosts, Electron requires setuid sandbox permissions on `chrome-sandbox`.

Preferred fix:

```bash
sudo chown root:root ./node_modules/electron/dist/chrome-sandbox
sudo chmod 4755 ./node_modules/electron/dist/chrome-sandbox
```

Temporary local-dev fallback (less secure):

```bash
CONSTRUCTOS_ALLOW_NO_SANDBOX=1 npm run start
# or
npm run start:no-sandbox
```

## Packaging

```bash
cd desktop
npm install
npm run package
```

Build installers:

```bash
# Build for current host platform
npm run dist

# Platform-specific
npm run dist:mac
npm run dist:win
npm run dist:linux
```

Artifacts are written to `desktop/release/`.

## Notes
- Cross-platform packaging generally works best when building on the same target OS (especially for signing/notarization).
- Add platform icons under `desktop/build/` if you want branded icons in installers.

## CI artifacts and signing
Workflow:
- `.github/workflows/desktop-artifacts.yml`

It builds installers for Linux, Windows, and macOS and uploads artifacts on pushes/PRs that touch `desktop/**`.

Tagging with `desktop-v*` also publishes release assets.

Optional signing/notarization secrets:
- `DESKTOP_CSC_LINK`
- `DESKTOP_CSC_KEY_PASSWORD`
- `DESKTOP_CSC_NAME`
- `DESKTOP_WIN_CSC_LINK`
- `DESKTOP_WIN_CSC_KEY_PASSWORD`
- `DESKTOP_APPLE_ID`
- `DESKTOP_APPLE_APP_SPECIFIC_PASSWORD`
- `DESKTOP_APPLE_TEAM_ID`

If these secrets are not configured, builds continue unsigned.
