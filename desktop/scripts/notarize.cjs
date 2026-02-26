const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const { notarize } = require("@electron/notarize");

module.exports = async function notarizeMac(context) {
  if (context.electronPlatformName !== "darwin") {
    return;
  }

  const requireNotarization = ["1", "true", "yes", "on"].includes(
    String(process.env.DESKTOP_REQUIRE_NOTARIZATION || "").trim().toLowerCase()
  );
  const appleId = String(process.env.APPLE_ID || "").trim();
  const appleIdPassword = String(process.env.APPLE_APP_SPECIFIC_PASSWORD || "").trim();
  const teamId = String(process.env.APPLE_TEAM_ID || "").trim();
  const appleApiKey = String(process.env.APPLE_API_KEY || "").trim();
  const appleApiKeyId = String(process.env.APPLE_API_KEY_ID || "").trim();
  const appleApiIssuer = String(process.env.APPLE_API_ISSUER || "").trim();

  const appName = context.packager.appInfo.productFilename;
  const appPath = path.join(context.appOutDir, `${appName}.app`);

  if (appleApiKey && appleApiKeyId && appleApiIssuer) {
    const apiKeyPath = path.join(os.tmpdir(), `constructos-apple-api-key-${Date.now()}.p8`);
    fs.writeFileSync(apiKeyPath, appleApiKey, { encoding: "utf8", mode: 0o600 });
    try {
      console.log(`Notarizing ${appPath} with Apple notarytool (API key auth)...`);
      await notarize({
        tool: "notarytool",
        appBundleId: context.packager.appInfo.id,
        appPath,
        appleApiKey: apiKeyPath,
        appleApiKeyId,
        appleApiIssuer,
      });
      return;
    } finally {
      try {
        fs.unlinkSync(apiKeyPath);
      } catch (_) {
        // Best-effort cleanup.
      }
    }
  }

  if (appleId && appleIdPassword && teamId) {
    console.log(`Notarizing ${appPath} with Apple notarytool (Apple ID auth)...`);
    await notarize({
      tool: "notarytool",
      appBundleId: context.packager.appInfo.id,
      appPath,
      appleId,
      appleIdPassword,
      teamId,
    });
    return;
  }

  const missingCredsMessage =
    "Skipping macOS notarization: provide either APPLE_API_KEY/APPLE_API_KEY_ID/APPLE_API_ISSUER or APPLE_ID/APPLE_APP_SPECIFIC_PASSWORD/APPLE_TEAM_ID.";
  if (requireNotarization) {
    throw new Error(
      `Notarization is required for this build, but credentials are missing. ${missingCredsMessage}`
    );
  }

  console.log(missingCredsMessage);
};
