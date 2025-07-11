const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const fs = require("fs");
const archiver = require("archiver");

function createWindow() {
	const win = new BrowserWindow({
		width: 800,
		height: 600,
		webPreferences: {
			preload: path.join(__dirname, "preload.js"),
			nodeIntegration: false,
			contextIsolation: true,
		},
	});
	win.loadURL(`file://${__dirname}/src/index.html`);
}

app.whenReady().then(createWindow);

ipcMain.handle("open-excel", async () => {
	const { canceled, filePaths } = await dialog.showOpenDialog({
		filters: [{ name: "Excel Files", extensions: ["xlsx", "xls"] }],
		properties: ["openFile"],
	});
	return canceled ? null : filePaths[0];
});

ipcMain.handle("save-zip", async () => {
	const { canceled, filePath } = await dialog.showSaveDialog({
		defaultPath: "comprimido_pacientes.zip",
	});
	return canceled ? null : filePath;
});

ipcMain.on("run-scrape", (event, { cedulas }) => {
	// Path absoluto al exe empacado
	const exePath = path.join(
		__dirname,
		"bin",
		process.platform === "win32" ? "backend.exe" : "backend"
	);
	// Llamamos al exe con la lista CSV como argumento
	const child = spawn(exePath, [cedulas.join(",")], {
		cwd: path.dirname(exePath),
	});

	child.stdout.on("data", (data) => {
		const msg = data.toString();
		const match = msg.match(/PROGRESS:(\d+)%/);
		if (match) {
			event.sender.send("progress-update", parseInt(match[1], 10));
		}
	});
	child.on("close", (code) => {
		event.sender.send("scrape-done", code === 0);
	});
});

ipcMain.handle("compress-docs", async (event, { inputDir }) => {
	const zipPath = await ipcMain.invoke("save-zip");
	if (!zipPath) return null;
	return new Promise((resolve, reject) => {
		const output = fs.createWriteStream(zipPath);
		const archive = archiver("zip");
		output.on("close", () => resolve(zipPath));
		archive.pipe(output);
		archive.directory(inputDir, false);
		archive.finalize();
	});
});
