const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("api", {
	openExcel: () => ipcRenderer.invoke("open-excel"),
	saveZip: () => ipcRenderer.invoke("save-zip"),
	runScrape: (cedulas) => ipcRenderer.send("run-scrape", { cedulas }),
	onProgress: (cb) =>
		ipcRenderer.on("progress-update", (e, percent) => cb(percent)),
	onDone: (cb) => ipcRenderer.on("scrape-done", (e, success) => cb(success)),
	compressDocs: (inputDir) => ipcRenderer.invoke("compress-docs", { inputDir }),
});
