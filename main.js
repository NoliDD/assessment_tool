// main.js (Electron main process)
const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

let pyProc = null;

const PORT = process.env.APP_PORT || '8501';
const URL  = `http://127.0.0.1:${PORT}`;

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
  // Prefer embedded venv (packaged), then dev venv, then system python
  const candidates = process.platform === 'win32'
    ? [
        resourcesPath('venv', 'Scripts', 'python.exe'),
        path.join(process.cwd(), 'venv', 'Scripts', 'python.exe'),
        'python', 'python3'
      ]
    : [
        resourcesPath('venv', 'bin', 'python'),
        path.join(process.cwd(), 'venv', 'bin', 'python'),
        '/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3',
        'python3', 'python'
      ];
  for (const c of candidates) {
    if (c.includes(path.sep)) { if (existsX(c)) return c; }
    else { return c; } // rely on PATH
  }
  return 'python3';
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
    webPreferences: { contextIsolation: true }
  });

  // Friendly loader so it’s not a white page
  // win.loadURL('data:text/html,' + encodeURIComponent('<h2 style="font-family:sans-serif;padding:24px">Starting…</h2>'));
  win.loadURL(
  'data:text/html;charset=utf-8,' +
  encodeURIComponent(`<!doctype html>
<meta charset="utf-8">
<style>
  body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;padding:24px}
</style>
<h2>Starting…</h2>`)
);

  // Resolve important paths
  const python = resolvePython();
  const appPy  = resourcesPath('app_entry.py');
  const rules  = resourcesPath('sku_coverage_rules.json');
  const taxonomy = resourcesPath('taxonomy.json');

  // Basic presence checks (app can still run without taxonomy/rules if you want)
  if (!fs.existsSync(appPy)) {
    dialog.showErrorBox('Missing file', `streamlit_app.py not found at:\n${appPy}`);
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

    // <-- pass absolute paths so Python never relies on cwd-only lookups
    SKU_COVERAGE_JSON: rules,             // for final_summary_agent
    TAXONOMY_JSON: taxonomy,              // fixes "No local 'taxonomy.json' found"
    APP_RESOURCES_DIR: RES_BASE,          // helpful generic base dir

    // Make project modules importable (agents/pages/etc.)
    PYTHONPATH: [
      RES_BASE,
      resourcesPath('agents'),
      resourcesPath('pages'),
      resourcesPath('reporting'),  // include if present
      resourcesPath('utils')       // include if present
    ].join(sep),

    // Help find python on macOS/Linux if PATH is minimal
    PATH: `${process.env.PATH || ''}:/usr/local/bin:/opt/homebrew/bin:/usr/bin`,
  };

  // Start Streamlit, using RES_BASE as the working directory
  pyProc = spawn(python, [
    '-m', 'streamlit', 'run', appPy,
    '--server.port', String(PORT),
    '--server.headless', 'true'
  ], { env, cwd: RES_BASE });

  pyProc.stdout.on('data', d => console.log('[py]', String(d)));
  pyProc.stderr.on('data', d => console.error('[py]', String(d)));
  pyProc.on('exit', code => console.log('Python exited:', code));

  try {
    await waitForHttp(URL, 60000);
    await win.loadURL(URL);
  } catch (err) {
    console.error('Server not ready:', err.message);
    win.webContents.openDevTools({ mode: 'detach' });
    win.webContents.executeJavaScript(
      `document.body.innerHTML="<pre style='padding:24px'>Failed to start server.\\n${err.message}</pre>"`
    );
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
