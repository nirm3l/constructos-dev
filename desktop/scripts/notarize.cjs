const path = require("node:path");
const { notarize } = require("@electron/notarize");

module.exports = async function notarizeMac(context) {
  if (context.electronPlatformName !== "darwin") {
    return;
  }

  const appleId = String(process.env.APPLE_ID || "").trim();
  const appleIdPassword = String(process.env.APPLE_APP_SPECIFIC_PASSWORD || "").trim();
  const teamId = String(process.env.APPLE_TEAM_ID || "").trim();

  if (!appleId || !appleIdPassword || !teamId) {
    console.log(
      "Skipping macOS notarization: APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID are not fully configured."
    );
    return;
  }

  const appName = context.packager.appInfo.productFilename;
  const appPath = path.join(context.appOutDir, `${appName}.app`);

  console.log(`Notarizing ${appPath} with Apple notarytool...`);
  await notarize({
    tool: "notarytool",
    appBundleId: context.packager.appInfo.id,
    appPath,
    appleId,
    appleIdPassword,
    teamId,
  });
};
