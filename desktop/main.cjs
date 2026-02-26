const http = require("node:http");
const https = require("node:https");
const path = require("node:path");
const fs = require("node:fs");
const { app, BrowserWindow, ipcMain, shell, Menu } = require("electron");

const DEFAULT_APP_URL = "http://127.0.0.1:8080";
const DEFAULT_STARTUP_TIMEOUT_MS = 45000;
const DEFAULT_RETRY_INTERVAL_MS = 1500;
const HEALTH_REQUEST_TIMEOUT_MS = 5000;
const CONFIG_FILE_NAME = "desktop-config.json";
const LOADING_PAGE_PATH = path.join(__dirname, "renderer", "loading.html");
const OFFLINE_PAGE_PATH = path.join(__dirname, "renderer", "offline.html");
const SETTINGS_PAGE_PATH = path.join(__dirname, "renderer", "settings.html");

let mainWindow = null;
let settingsWindow = null;
let runtimeConfig = null;
let bootstrapPromise = null;

function readArgValue(flagName) {
  const prefix = `--${flagName}=`;
  const raw = process.argv.find((arg) => arg.startsWith(prefix));
  if (!raw) return "";
  return raw.slice(prefix.length).trim();
}

function sanitizeUrl(rawValue, fallbackValue) {
  const fallback = String(fallbackValue || "").trim();
  const candidate = String(rawValue || "").trim() || fallback;
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error("Only http/https URLs are supported.");
    }
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return fallback;
  }
}

function parsePositiveInt(rawValue, fallbackValue, minValue, maxValue) {
  const parsed = Number.parseInt(String(rawValue || "").trim(), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallbackValue;
  return Math.min(Math.max(parsed, minValue), maxValue);
}

function getConfigFilePath() {
  return path.join(app.getPath("userData"), CONFIG_FILE_NAME);
}

function readPersistedConfig() {
  try {
    const raw = fs.readFileSync(getConfigFilePath(), "utf8");
    const payload = JSON.parse(raw);
    if (!payload || typeof payload !== "object") return {};
    return payload;
  } catch {
    return {};
  }
}

function writePersistedConfig(config) {
  try {
    const targetPath = getConfigFilePath();
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.writeFileSync(
      targetPath,
      JSON.stringify(
        {
          appUrl: config.appUrl,
          healthUrl: config.healthUrl,
          startupTimeoutMs: config.startupTimeoutMs,
          retryIntervalMs: config.retryIntervalMs,
        },
        null,
        2
      ),
      "utf8"
    );
  } catch {
    // Ignore config persistence errors to avoid blocking startup.
  }
}

function normalizeHttpUrlOrThrow(rawValue, fieldName) {
  const text = String(rawValue || "").trim();
  if (!text) {
    throw new Error(`${fieldName} is required.`);
  }
  const parsed = new URL(text);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`${fieldName} must use http:// or https://.`);
  }
  return parsed.toString().replace(/\/$/, "");
}

function resolveRuntimeConfig() {
  const persisted = readPersistedConfig();
  const appUrl = sanitizeUrl(
    readArgValue("app-url") ||
      process.env.CONSTRUCTOS_APP_URL ||
      persisted.appUrl,
    DEFAULT_APP_URL
  );
  const defaultHealthUrl = `${appUrl}/api/health`;
  const healthUrl = sanitizeUrl(
    readArgValue("health-url") ||
      process.env.CONSTRUCTOS_HEALTH_URL ||
      persisted.healthUrl,
    defaultHealthUrl
  );
  const startupTimeoutMs = parsePositiveInt(
    readArgValue("startup-timeout-ms") ||
      process.env.CONSTRUCTOS_STARTUP_TIMEOUT_MS ||
      persisted.startupTimeoutMs,
    DEFAULT_STARTUP_TIMEOUT_MS,
    1000,
    300000
  );
  const retryIntervalMs = parsePositiveInt(
    readArgValue("retry-interval-ms") ||
      process.env.CONSTRUCTOS_RETRY_INTERVAL_MS ||
      persisted.retryIntervalMs,
    DEFAULT_RETRY_INTERVAL_MS,
    250,
    30000
  );
  return {
    appUrl,
    healthUrl,
    startupTimeoutMs,
    retryIntervalMs,
  };
}

function requestStatusCode(urlString, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    try {
      const parsed = new URL(urlString);
      const transport = parsed.protocol === "https:" ? https : http;
      const req = transport.request(
        parsed,
        {
          method: "GET",
          timeout: timeoutMs,
          headers: {
            Accept: "application/json,text/plain,*/*",
          },
        },
        (res) => {
          const statusCode = Number(res.statusCode || 0);
          res.resume();
          done({
            ok: statusCode >= 200 && statusCode < 300,
            statusCode,
          });
        }
      );
      req.on("timeout", () => {
        req.destroy(new Error("timeout"));
      });
      req.on("error", () => {
        done({
          ok: false,
          statusCode: 0,
        });
      });
      req.end();
    } catch {
      done({
        ok: false,
        statusCode: 0,
      });
    }
  });
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function waitForBackend(config) {
  const deadline = Date.now() + config.startupTimeoutMs;
  let lastStatusCode = 0;
  while (Date.now() < deadline) {
    const probe = await requestStatusCode(config.healthUrl, HEALTH_REQUEST_TIMEOUT_MS);
    lastStatusCode = probe.statusCode;
    if (probe.ok) {
      return {
        ready: true,
        statusCode: lastStatusCode,
      };
    }
    await sleep(config.retryIntervalMs);
  }
  return {
    ready: false,
    statusCode: lastStatusCode,
  };
}

function getAppOrigin() {
  try {
    return new URL(runtimeConfig.appUrl).origin;
  } catch {
    return "";
  }
}

function isAllowedNavigation(targetUrl) {
  if (!targetUrl) return false;
  if (targetUrl === "about:blank") return true;
  if (targetUrl.startsWith("file:")) return true;
  try {
    const parsed = new URL(targetUrl);
    return parsed.origin === getAppOrigin();
  } catch {
    return false;
  }
}

function canOpenExternal(targetUrl) {
  try {
    const parsed = new URL(targetUrl);
    return (
      parsed.protocol === "http:" ||
      parsed.protocol === "https:" ||
      parsed.protocol === "mailto:"
    );
  } catch {
    return false;
  }
}

function openExternalSafe(targetUrl) {
  if (!canOpenExternal(targetUrl)) return;
  void shell.openExternal(targetUrl);
}

function attachNavigationGuards(windowRef) {
  windowRef.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedNavigation(url)) {
      return { action: "allow" };
    }
    openExternalSafe(url);
    return { action: "deny" };
  });

  windowRef.webContents.on("will-navigate", (event, url) => {
    if (isAllowedNavigation(url)) return;
    event.preventDefault();
    openExternalSafe(url);
  });
}

async function showOfflinePage(windowRef, statusCode) {
  await windowRef.loadFile(OFFLINE_PAGE_PATH, {
    query: {
      appUrl: runtimeConfig.appUrl,
      healthUrl: runtimeConfig.healthUrl,
      startupTimeoutMs: String(runtimeConfig.startupTimeoutMs),
      statusCode: statusCode > 0 ? String(statusCode) : "",
    },
  });
}

async function bootstrapAppWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
  if (bootstrapPromise) return bootstrapPromise;

  bootstrapPromise = (async () => {
    await mainWindow.loadFile(LOADING_PAGE_PATH, {
      query: {
        appUrl: runtimeConfig.appUrl,
      },
    });
    const probe = await waitForBackend(runtimeConfig);
    if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
    if (probe.ready) {
      await mainWindow.loadURL(runtimeConfig.appUrl);
      return { ok: true, online: true };
    }
    await showOfflinePage(mainWindow, probe.statusCode);
    return { ok: true, online: false, statusCode: probe.statusCode };
  })().finally(() => {
    bootstrapPromise = null;
  });

  return bootstrapPromise;
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    title: "ConstructOS",
    width: 1440,
    height: 920,
    minWidth: 1120,
    minHeight: 740,
    backgroundColor: "#0b111a",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  attachNavigationGuards(mainWindow);
  void bootstrapAppWindow();

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function createMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac
      ? [
          {
            label: "ConstructOS",
            submenu: [
              { role: "about" },
              { type: "separator" },
              {
                label: "Connection Settings",
                accelerator: "CmdOrCtrl+,",
                click: () => {
                  openSettingsWindow();
                },
              },
              { type: "separator" },
              { role: "services" },
              { type: "separator" },
              { role: "hide" },
              { role: "hideOthers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]
      : []),
    {
      label: "File",
      submenu: [
        {
          label: "Connection Settings",
          accelerator: "CmdOrCtrl+,",
          click: () => {
            openSettingsWindow();
          },
        },
        { type: "separator" },
        ...(isMac ? [{ role: "close" }] : [{ role: "quit" }]),
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function openSettingsWindow() {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.focus();
    return;
  }
  settingsWindow = new BrowserWindow({
    title: "Connection Settings",
    width: 560,
    height: 420,
    minWidth: 520,
    minHeight: 380,
    parent: mainWindow || undefined,
    modal: false,
    resizable: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  attachNavigationGuards(settingsWindow);
  void settingsWindow.loadFile(SETTINGS_PAGE_PATH);
  settingsWindow.on("closed", () => {
    settingsWindow = null;
  });
}

ipcMain.handle("constructos:get-runtime-config", () => {
  return {
    ...runtimeConfig,
    desktopVersion: app.getVersion(),
    platform: process.platform,
  };
});

ipcMain.handle("constructos:retry-connection", async () => {
  return bootstrapAppWindow();
});

ipcMain.handle("constructos:open-settings", () => {
  openSettingsWindow();
  return { ok: true };
});

ipcMain.handle("constructos:update-endpoint", async (_event, payload) => {
  const nextAppUrl = normalizeHttpUrlOrThrow(payload?.appUrl, "App URL");
  const defaultHealthUrl = `${nextAppUrl}/api/health`;
  const healthRaw = String(payload?.healthUrl || "").trim();
  const nextHealthUrl = healthRaw
    ? normalizeHttpUrlOrThrow(healthRaw, "Health URL")
    : defaultHealthUrl;
  runtimeConfig = {
    ...runtimeConfig,
    appUrl: nextAppUrl,
    healthUrl: nextHealthUrl,
  };
  writePersistedConfig(runtimeConfig);
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.close();
  }
  await bootstrapAppWindow();
  return {
    ok: true,
    runtimeConfig: { ...runtimeConfig },
  };
});

ipcMain.handle("constructos:open-in-browser", async () => {
  await shell.openExternal(runtimeConfig.appUrl);
  return { ok: true };
});

ipcMain.handle("constructos:quit", () => {
  app.quit();
  return { ok: true };
});

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(() => {
    runtimeConfig = resolveRuntimeConfig();
    writePersistedConfig(runtimeConfig);
    if (process.platform === "win32") {
      app.setAppUserModelId("dev.constructos.desktop");
    }
    createMenu();
    createMainWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow();
      }
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
