// main.js (Electron main process)
const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

let pyProc = null;

const PORT = process.env.APP_PORT || '8501';
const APP_URL = `http://127.0.0.1:${PORT}`;
const HEALTH_URL = `${APP_URL}/_stcore/health`; // Streamlit built-in health

// Resolve a base resources directory for dev vs packaged
function resolveResourcesBase() {
  if (app.isPackaged) return process.resourcesPath; // .../Contents/Resources
  // In dev, prefer ./resources if it exists; otherwise project root
  const devRes = path.join(process.cwd(), 'resources');
  return fs.existsSync(path.join(devRes, 'streamlit_app.py')) ? devRes : process.cwd();
}
const RES_BASE = resolveResourcesBase();

function resourcesPath(...p) {
  return path.join(RES_BASE, ...p);
}

function existsX(p) {
  try { fs.accessSync(p, fs.constants.X_OK); return true; } catch { return false; }
}

function resolvePython() {
  if (process.platform === 'win32') {
    const embedded = resourcesPath('venv', 'Scripts', 'python.exe');
    if (fs.existsSync(embedded)) return embedded;
    return 'python';
  } else {
    const embedded = resourcesPath('venv', 'bin', 'python3');
    if (fs.existsSync(embedded)) return embedded;
    return 'python3';
  }
}



function waitForHttp(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const req = http.get(url, res => {
        if ((res.statusCode || 0) < 600) resolve();
        else setTimeout(next, 300);
      });
      req.on('error', () => setTimeout(next, 300));
      req.end();
    };
    const next = () => (Date.now() > deadline ? reject(new Error('Server not ready')) : tryOnce());
    tryOnce();
  });
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 900, minHeight: 600,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  });

  // Friendly loader so it’s not a white page (UTF-8 safe)
  win.loadURL(
    'data:text/html;charset=utf-8,' +
    encodeURIComponent(`<!doctype html>
<meta charset="utf-8">
<style>
  body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;padding:24px}
</style>
<h2>Starting…</h2>`)
  );

  // Keep the window pinned to your local Streamlit app
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(APP_URL)) return { action: 'allow' };
    shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith(APP_URL)) { e.preventDefault(); shell.openExternal(url); }
  });

  // Resolve important paths
  const python = resolvePython();
  const appPy  = resourcesPath('app_entry.py'); // entry file
  const rules  = resourcesPath('sku_coverage_rules.json');
  const taxonomy = resourcesPath('taxonomy.json');

  // Basic presence checks
  if (!fs.existsSync(appPy)) {
    dialog.showErrorBox('Missing file', `app_entry.py not found at:\n${appPy}`);
    return;
  }
  console.log('isPackaged:', app.isPackaged);
  console.log('RES_BASE   :', RES_BASE);
  console.log('python     :', python);
  console.log('appPy      :', appPy);
  console.log('rules JSON :', rules, 'exists:', fs.existsSync(rules));
  console.log('taxonomy   :', taxonomy, 'exists:', fs.existsSync(taxonomy));

  const cfg = resourcesPath('.streamlit', 'config.toml');
  console.log('Using Streamlit config:', cfg, 'exists:', fs.existsSync(cfg));

  // Build env for Python
  const sep = process.platform === 'win32' ? ';' : ':';
  const env = {
    ...process.env,
    APP_VERSION: app.getVersion(),
    STREAMLIT_CONFIG: cfg,
    BROWSER: 'none',
    STREAMLIT_BROWSER_GATHER_USAGE_STATS: 'false',

    // pass absolute paths so Python never relies on cwd-only lookups
    SKU_COVERAGE_JSON: rules,
    TAXONOMY_JSON: taxonomy,
    APP_RESOURCES_DIR: RES_BASE,

    // Make project modules importable (agents/pages/etc.)
    PYTHONPATH: [
      RES_BASE,
      resourcesPath('agents'),
      resourcesPath('pages'),
      resourcesPath('reporting'),
      resourcesPath('utils')
    ].join(sep),

    // Help find python on macOS/Linux if PATH is minimal
    PATH: `${process.env.PATH || ''}:/usr/local/bin:/opt/homebrew/bin:/usr/bin`,
  };

  // Start Streamlit, using RES_BASE as the working directory
  pyProc = spawn(python, [
    '-m', 'streamlit', 'run', appPy,
    '--server.port', String(PORT),
    '--server.headless', 'true',
    '--server.address', '127.0.0.1' // restrict to localhost
  ], { env, cwd: RES_BASE });

  pyProc.stdout.on('data', d => console.log('[py]', String(d)));
  pyProc.stderr.on('data', d => console.error('[py]', String(d)));
  pyProc.on('exit', code => console.log('Python exited:', code));

  try {
    // Prefer health URL, then load app (fallback to app URL even if health fails)
    await waitForHttp(HEALTH_URL, 60000);
    await win.loadURL(APP_URL);
  } catch (err) {
    console.error('Health check failed:', err.message);
    // Try to load the app anyway after a short delay
    setTimeout(() => win.loadURL(APP_URL), 1500);
  }

  win.webContents.on('did-fail-load', (e, code, desc) => {
    console.error('did-fail-load', code, desc);
    win.webContents.openDevTools({ mode: 'detach' });
  });

  win.on('closed', () => { try { pyProc && pyProc.kill(); } catch {} });
}

// catch async errors so they don’t crash silently
process.on('unhandledRejection', (err) => {
  console.error('unhandledRejection:', err);
});

app.whenReady().then(() => createWindow()).catch(err => {
  console.error('createWindow failed:', err);
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow().catch(console.error); });
