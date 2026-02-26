const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("constructosDesktop", {
  getRuntimeConfig: () => ipcRenderer.invoke("constructos:get-runtime-config"),
  retryConnection: () => ipcRenderer.invoke("constructos:retry-connection"),
  openSettings: () => ipcRenderer.invoke("constructos:open-settings"),
  updateEndpoint: (payload) => ipcRenderer.invoke("constructos:update-endpoint", payload),
  openInBrowser: () => ipcRenderer.invoke("constructos:open-in-browser"),
  quit: () => ipcRenderer.invoke("constructos:quit"),
});
