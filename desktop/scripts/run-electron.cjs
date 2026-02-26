const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

function getElectronBinaryPath() {
  const electronModulePath = require.resolve("electron");
  const electronModuleDir = path.dirname(electronModulePath);
  return path.join(electronModuleDir, "dist", "electron");
}

function getChromeSandboxPath() {
  const electronModulePath = require.resolve("electron");
  const electronModuleDir = path.dirname(electronModulePath);
  return path.join(electronModuleDir, "dist", "chrome-sandbox");
}

function hasValidSetuidSandbox(pathToSandbox) {
  try {
    const stats = fs.statSync(pathToSandbox);
    const isRootOwner = stats.uid === 0;
    const isSetuid4755 = (stats.mode & 0o4777) === 0o4755;
    return isRootOwner && isSetuid4755;
  } catch {
    return false;
  }
}

function printLinuxSandboxHelp(pathToSandbox) {
  console.error("");
  console.error("Electron Linux sandbox is not configured correctly.");
  console.error("Preferred fix (secure):");
  console.error(`  sudo chown root:root "${pathToSandbox}"`);
  console.error(`  sudo chmod 4755 "${pathToSandbox}"`);
  console.error("");
  console.error("Temporary local-dev fallback (less secure):");
  console.error("  CONSTRUCTOS_ALLOW_NO_SANDBOX=1 npm run start");
  console.error("  # or");
  console.error("  npm run start:no-sandbox");
  console.error("");
}

function runElectron(args) {
  const electronBinary = getElectronBinaryPath();
  const child = spawn(electronBinary, args, {
    stdio: "inherit",
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.exitCode = 1;
      return;
    }
    process.exitCode = Number(code || 0);
  });
}

function main() {
  const userArgs = process.argv.slice(2);
  const appDir = path.resolve(__dirname, "..");
  const baseArgs = [appDir, ...userArgs];

  if (process.platform !== "linux") {
    runElectron(baseArgs);
    return;
  }

  const sandboxPath = getChromeSandboxPath();
  const allowNoSandbox = String(process.env.CONSTRUCTOS_ALLOW_NO_SANDBOX || "").trim() === "1";
  const validSandbox = hasValidSetuidSandbox(sandboxPath);

  if (validSandbox) {
    runElectron(baseArgs);
    return;
  }

  if (allowNoSandbox) {
    console.warn("Starting Electron with --no-sandbox (local development only).");
    runElectron(["--no-sandbox", ...baseArgs]);
    return;
  }

  printLinuxSandboxHelp(sandboxPath);
  process.exitCode = 1;
}

main();
