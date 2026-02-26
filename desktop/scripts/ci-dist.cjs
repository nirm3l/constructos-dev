const { spawnSync } = require("node:child_process");
const path = require("node:path");

const optionalEnvKeys = [
  "CSC_LINK",
  "CSC_KEY_PASSWORD",
  "CSC_NAME",
  "WIN_CSC_LINK",
  "WIN_CSC_KEY_PASSWORD",
  "APPLE_ID",
  "APPLE_APP_SPECIFIC_PASSWORD",
  "APPLE_TEAM_ID",
];

for (const key of optionalEnvKeys) {
  const value = process.env[key];
  if (typeof value === "string" && value.trim() === "") {
    delete process.env[key];
  }
}

const electronBuilderBin =
  process.platform === "win32"
    ? path.join(__dirname, "..", "node_modules", ".bin", "electron-builder.cmd")
    : path.join(__dirname, "..", "node_modules", ".bin", "electron-builder");

const result = spawnSync(electronBuilderBin, ["--publish", "never"], {
  stdio: "inherit",
  env: process.env,
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
