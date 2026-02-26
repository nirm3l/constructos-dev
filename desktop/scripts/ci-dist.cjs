const { spawnSync } = require("node:child_process");
const optionalEnvKeys = [
  "CSC_LINK",
  "CSC_KEY_PASSWORD",
  "CSC_NAME",
  "WIN_CSC_LINK",
  "WIN_CSC_KEY_PASSWORD",
  "APPLE_ID",
  "APPLE_APP_SPECIFIC_PASSWORD",
  "APPLE_TEAM_ID",
  "APPLE_API_KEY",
  "APPLE_API_KEY_ID",
  "APPLE_API_ISSUER",
];

for (const key of optionalEnvKeys) {
  const value = process.env[key];
  if (typeof value === "string" && value.trim() === "") {
    delete process.env[key];
  }
}

const npmExecutable = process.platform === "win32" ? "npm.cmd" : "npm";

const result = spawnSync(npmExecutable, ["exec", "--", "electron-builder", "--publish", "never"], {
  stdio: "inherit",
  env: process.env,
  shell: process.platform === "win32",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
