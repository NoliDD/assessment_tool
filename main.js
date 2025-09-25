// main.js (Electron main process) — version-agnostic (3.10 or 3.12), runtime-agnostic
const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

let pyProc = null;

const PORT = process.env.APP_PORT || '8501';
const APP_URL = `http://127.0.0.1:${PORT}`;
const HEALTH_URL = `${APP_URL}/_stcore/health`;

// ----------------------------- helpers -----------------------------

function resolveResourcesBase() {
  if (app.isPackaged) return process.resourcesPath; // .../Contents/Resources
  const devRes = path.join(process.cwd(), 'resources');
  return fs.existsSync(path.join(devRes, 'streamlit_app.py')) ? devRes : process.cwd();
}
const RES_BASE = resolveResourcesBase();

function resourcesPath(...p) { return path.join(RES_BASE, ...p); }

function existsX(p) { try { fs.accessSync(p, fs.constants.X_OK); return true; } catch { return false; } }

function resolvePython() {
  if (process.platform === 'win32') {
    const embedded = resourcesPath('venv', 'Scripts', 'python.exe');
    if (fs.existsSync(embedded)) return embedded;
    return 'python';
  } else {
    const candidates = [
      resourcesPath('venv', 'bin', 'python3.12'),
      resourcesPath('venv', 'bin', 'python3.11'),
      resourcesPath('venv', 'bin', 'python3.10'),
      resourcesPath('venv', 'bin', 'python3'),
      resourcesPath('venv', 'bin', 'python'),
      resourcesPath('python','bin','python3'),   // ← standalone runtime
      resourcesPath('python','bin','python'),
    ];
    for (const c of candidates) { if (fs.existsSync(c)) return c; }
    return process.env.PYTHON || 'python3';
  }
}

// Find a directory name like "python3.12" or "python3.10" under <root>/lib
function discoverStdlibDir(stdlibRoot) {
  try {
    const dirs = fs.readdirSync(stdlibRoot, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => d.name)
      .filter(n => /^python3\.\d+$/.test(n))
      .sort()
      .reverse();
    return dirs[0] || null;
  } catch { return null; }
}

// Detect packaged runtime:
//  - Standalone runtime at Resources/python
//  - Or a Python.framework at Resources/Python.framework/Versions/<ver>
function detectPackagedRuntime() {
  if (!app.isPackaged) return { mode: 'dev' };

  // Prefer standalone if present
  const pyStandalone = resourcesPath('python');
  if (fs.existsSync(pyStandalone) && fs.existsSync(path.join(pyStandalone, 'bin'))) {
    const pyHome = pyStandalone;
    const stdlibRoot = path.join(pyHome, 'lib');
    const stdlibDir = discoverStdlibDir(stdlibRoot) || 'python3.10';
    return {
      mode: 'standalone',
      PYHOME: pyHome,
      stdlibRoot,
      stdlibDir,
      extraEnv: {}, // no DYLD needed for standalone
    };
  }

  // Otherwise try a framework
  const fwRoot = resourcesPath('Python.framework', 'Versions');
  if (fs.existsSync(fwRoot)) {
    // Pick highest version folder, e.g. "3.12" or "3.10"
    let best = null;
    try {
      const vers = fs.readdirSync(fwRoot, { withFileTypes: true })
        .filter(d => d.isDirectory() && /^\d+\.\d+/.test(d.name))
        .map(d => d.name)
        .sort()
        .reverse();
      best = vers[0] || null;
    } catch {}
    if (best) {
      const pyHome = path.join(fwRoot, best);
      const stdlibRoot = path.join(pyHome, 'lib');
      const stdlibDir = discoverStdlibDir(stdlibRoot) || `python${best}`;
      return {
        mode: 'framework',
        PYHOME: pyHome,
        stdlibRoot,
        stdlibDir,
        extraEnv: { DYLD_FRAMEWORK_PATH: RES_BASE }, // tell dyld where the framework lives
      };
    }
  }

  return { mode: 'none' };
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

// ------------------------------ main -------------------------------

async function createWindow() {
  const win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 900, minHeight: 600,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true }
  });

  // Friendly loader
  win.loadURL(
    'data:text/html;charset=utf-8,' +
    encodeURIComponent(`<!doctype html>
<meta charset="utf-8">
<style>
  body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;padding:24px}
  .spin{animation:s 1s linear infinite}@keyframes s{to{transform:rotate(1turn)}}
</style>
<h2>Starting…</h2><div class="spin">⏳</div>`)
  );

  // Keep navigation inside app; external links open in browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(APP_URL)) return { action: 'allow' };
    shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith(APP_URL)) { e.preventDefault(); shell.openExternal(url); }
  });

  // Important paths
  const python = resolvePython();
  const appPy  = resourcesPath('app_entry.py');
  const compiledEntry = resourcesPath('app_entry');
  const cfg    = resourcesPath('.streamlit', 'config.toml');
  const rules  = resourcesPath('sku_coverage_rules.json');
  const taxonomy = resourcesPath('taxonomy.json');

  if (!fs.existsSync(appPy) && !fs.existsSync(compiledEntry)) {
    dialog.showErrorBox('Missing entry', `Could not find a launcher:\n- ${appPy}\n- ${compiledEntry}`);
    return;
  }

  // Build env
  const sep = process.platform === 'win32' ? ';' : ':';

  const appModulePaths = [
    RES_BASE,
    resourcesPath('agents'),
    resourcesPath('pages'),
    resourcesPath('reporting'),
    resourcesPath('utils'),
  ];

  // Detect packaged runtime (standalone or framework). In dev, we don't set PYHOME.
  const rt = detectPackagedRuntime();
  let PYHOME = null, PYTHONPATH = appModulePaths.join(sep);
  let extraEnv = {};

  if (rt.mode === 'standalone' || rt.mode === 'framework') {
    PYHOME = rt.PYHOME;
    // Append stdlib + lib-dynload to PYTHONPATH (version-agnostic)
    PYTHONPATH = appModulePaths.concat([
      path.join(rt.stdlibRoot, rt.stdlibDir),
      path.join(rt.stdlibRoot, rt.stdlibDir, 'lib-dynload'),
    ]).join(sep);
    extraEnv = rt.extraEnv || {};
  }

  const baseEnv = {
    ...process.env,
    APP_VERSION: app.getVersion(),
    STREAMLIT_CONFIG: cfg,
    BROWSER: 'none',
    STREAMLIT_BROWSER_GATHER_USAGE_STATS: 'false',

    // Absolute resource paths for your app
    SKU_COVERAGE_JSON: rules,
    TAXONOMY_JSON: taxonomy,
    APP_RESOURCES_DIR: RES_BASE,

    // Ensure your modules are importable
    PYTHONPATH,

    // Help PATH on macOS/Linux
    PATH: `${process.env.PATH || ''}:/usr/local/bin:/opt/homebrew/bin:/usr/bin`,
  };

  const env = {
    ...baseEnv,
    // Only set PYTHONHOME if we detected a packaged runtime
    ...(PYHOME ? { PYTHONHOME: PYHOME } : {}),
    ...extraEnv,
  };

  // Logs
  console.log('isPackaged:', app.isPackaged);
  console.log('RES_BASE   :', RES_BASE);
  console.log('python     :', python);
  console.log('appPy      :', appPy);
  console.log('rules JSON :', rules, 'exists:', fs.existsSync(rules));
  console.log('taxonomy   :', taxonomy, 'exists:', fs.existsSync(taxonomy));
  console.log('Using Streamlit config:', cfg, 'exists:', fs.existsSync(cfg));
  console.log('Runtime mode:', rt.mode);
  console.log('PYTHONHOME :', env.PYTHONHOME || '(none)');
  console.log('PYTHONPATH :', env.PYTHONPATH);
  if (env.DYLD_FRAMEWORK_PATH) console.log('DYLD_FRAMEWORK_PATH:', env.DYLD_FRAMEWORK_PATH);

  // Choose command
  let cmd, args;
  if (fs.existsSync(compiledEntry) && existsX(compiledEntry)) {
    cmd = compiledEntry; args = [];
  } else {
    cmd = python; args = [appPy];
  }

  const childEnv = { ...env, STREAMLIT_SERVER_PORT: String(PORT) };
  pyProc = spawn(cmd, args, { env: childEnv, cwd: RES_BASE });

  pyProc.stdout.on('data', d => process.stdout.write('[py] ' + d));
  pyProc.stderr.on('data', d => process.stderr.write('[py] ' + d));
  pyProc.on('exit', code => console.log('Python exited:', code));

  try {
    await waitForHttp(HEALTH_URL, 60000);
    await win.loadURL(APP_URL);
  } catch (err) {
    console.error('Health check failed:', err.message);
    setTimeout(() => win.loadURL(APP_URL), 1500);
  }

  win.webContents.on('did-fail-load', (e, code, desc) => {
    console.error('did-fail-load', code, desc);
    win.webContents.openDevTools({ mode: 'detach' });
  });

  win.on('closed', () => { try { pyProc && pyProc.kill(); } catch {} });
}

// ---------------------------- lifecycle ----------------------------

process.on('unhandledRejection', (err) => { console.error('unhandledRejection:', err); });

app.whenReady()
  .then(() => createWindow())
  .catch(err => { console.error('createWindow failed:', err); });

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow().catch(console.error); });