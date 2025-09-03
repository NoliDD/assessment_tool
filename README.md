# Merchant Data Assessment Tool (Desktop)

A cross‑platform desktop app for assessing merchant catalog data and generating an AI‑assisted report. The UI is built in **Streamlit** (Python) and packaged as a desktop app with **Electron** (Node.js). The app can run entirely offline (except for calls to the OpenAI API when enabled).

---

## ✨ What the app does

* **Data ingestion**: Upload a merchant CSV/XLSX and standardize columns automatically.
* **Attribute agents**: Run a suite of agents (Brand, Size, Category/Taxonomy, Images, UPC, SNAP, etc.) on the catalog.
* **Taxonomy mapping**: (optional) AI‑assisted mapping against allowed L1/L2 pairs for the selected vertical.
* **Final summary**: Decide GP eligibility using rules from `sku_coverage_rules.json` + qualitative checks. An LLM writes a concise verdict.
* **Chat with report**: Ask questions about the results and the criteria document.
* **Downloads**: Export the full assessed dataset and curated samples for manual review.
* **Usage tracking**: Token/cost estimates per session.
* **Desktop wrapper**: Electron launches a local Streamlit server and loads it in a native window.

---

## 🧩 Architecture (high level)

```
Electron (main.js)
  └─ Spawns Python (venv) → runs Streamlit (app_entry.py)
     └─ Streamlit pages
        ├─ Home (streamlit_app.py)
        ├─ Chat (pages/2_Chat_with_Report.py)
        ├─ ui.py (footer, shared UI)
        └─ agents/* (attribute checks, reporting, final summary)
```

* Electron sets env vars (`APP_VERSION`, `SKU_COVERAGE_JSON`, `TAXONOMY_JSON`, etc.), starts:

  ```bash
  python -m streamlit run app_entry.py --server.port 8501 --server.headless true --server.address 127.0.0.1
  ```
* Electron waits on Streamlit’s health URL (`/_stcore/health`) and then loads the app URL in a window.

---

## 📁 Project structure (suggested)

```
.
├─ app_entry.py                  # Streamlit navigation entry (Home + Chat)
├─ streamlit_app.py              # Home page (run assessment, results)
├─ pages/
│  └─ 2_Chat_with_Report.py      # Chat page
├─ agents/                       # Attribute “agents” (Category, SNAP, etc.)
│  ├─ base_agent.py
│  ├─ category_agent.py
│  └─ final_summary_agent.py
├─ utils/                        # Utilities (validation, helpers)
│  └─ __init__.py
├─ ui.py                         # add_footer and shared UI helpers
├─ taxonomy.json                 # embedded taxonomy (optional but recommended)
├─ sku_coverage_rules.json       # embedded rules used by final summary
├─ assessment_instructions.yaml  # criteria used by Chat with Report
├─ venv/                         # Python virtual env (bundled for desktop build)
├─ requirements.txt
├─ .streamlit/config.toml        # Streamlit defaults (hide Deploy, theme, etc.)
├─ main.js                       # Electron launcher (spawns Streamlit)
├─ package.json                  # Electron/Electron-Builder config
└─ splash.html                   # (optional) “Starting…” splash
```

> In dev you don’t need to bundle `venv/` yet. For production desktop builds, include a **fully installed** venv so end users do not need Python.

---

## ✅ Prerequisites

* **Python** 3.10+
* **Node.js** 18+ (includes npm)
* macOS: Homebrew (optional)
* Windows: PowerShell + Git Bash recommended

---

## 🚀 Quick start (dev)

### 1) Python environment

```bash
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Run Streamlit directly (optional sanity check):

```bash
streamlit run app_entry.py
```

### 2) Electron dev

```bash
npm install
npm run start    # launches Electron, which spawns Streamlit for you
```

> In this flow, **Electron** starts your Streamlit server and opens the desktop window. You don’t need a separate `streamlit run` process.

---

## 🧱 Streamlit configuration

Create `.streamlit/config.toml` to customize Streamlit inside the desktop app:

```toml
[client]
toolbarMode = "minimal"
showSidebarNavigation = true

[server]
headless = true

[theme]
base = "dark"
```

Electron points to this file via the `STREAMLIT_CONFIG` env var in `main.js`:

```js
env.STREAMLIT_CONFIG = resourcesPath('.streamlit','config.toml');
```

---

## 🖼 Branding (icon + footer)

* App icon: place PNG/ICNS/ICO in your build config (`package.json → build`).
* Footer: the `add_footer()` helper renders a sticky footer; version is injected from Electron:

  ```js
  env.APP_VERSION = app.getVersion();
  env.APP_AUTHOR  = authorName;
  env.APP_CONTACT = authorEmail;
  ```

  In Python:

  ```python
  add_footer(author=os.getenv("APP_AUTHOR","David"),
             contact_email=os.getenv("APP_CONTACT","xyz@gmail.com"),
             extra=f"v{os.getenv('APP_VERSION','dev')}")
  ```

---

## 🧩 Rules & taxonomy (embedded files)

Electron passes absolute paths to Python via env vars; the app reads these in `streamlit_app.py`:

* `SKU_COVERAGE_JSON` → `sku_coverage_rules.json`
* `TAXONOMY_JSON` → `taxonomy.json`

Ship both files in `extraResources` so they’re available at runtime (see build section below).

---

## 🔒 Security defaults

* Streamlit binds to **localhost** only: `--server.address 127.0.0.1`
* `BrowserWindow` uses: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, `webSecurity: true`
* Navigation is locked to `http://127.0.0.1:<port>`; external links open in the OS browser
* Secrets are read from env vars (never hard‑code API keys)

---

## 🧪 Running tests / sanity checks

* Start Electron: `npm run start`
* Verify health URL: open `http://127.0.0.1:8501/_stcore/health`
* Check logs in the terminal for missing paths, ports already in use, etc.

---

## 🏗 Build a desktop app

The project uses **electron‑builder**. Builds are created from `package.json` fields.

### 1) Make sure your build config lists resources to include

In `package.json`:

```jsonc
{
  "name": "data-assessment-tool",
  "version": "1.0.0",
  "main": "main.js",
  "build": {
    "appId": "com.yourorg.data-assessment-tool",
    "files": [
      "main.js",
      "package.json"
    ],
    "extraResources": [
      { "from": "app_entry.py", "to": "app_entry.py" },
      { "from": "streamlit_app.py", "to": "streamlit_app.py" },
      { "from": "pages", "to": "pages" },
      { "from": "agents", "to": "agents" },
      { "from": "utils", "to": "utils" },
      { "from": "ui.py", "to": "ui.py" },
      { "from": ".streamlit", "to": ".streamlit" },
      { "from": "taxonomy.json", "to": "taxonomy.json" },
      { "from": "sku_coverage_rules.json", "to": "sku_coverage_rules.json" },
      { "from": "venv", "to": "venv" } // include a fully-installed venv for production
    ]
  },
  "scripts": {
    "start": "electron .",
    "pack": "electron-builder --dir",
    "dist:mac": "electron-builder --mac",
    "dist:win": "electron-builder --win",
    "dist:linux": "electron-builder --linux"
  },
  "devDependencies": {
    "electron": "^30",
    "electron-builder": "^24"
  }
}
```

> Tip: For dev builds you can omit the `venv` from `extraResources`. For production releases, include it **after** running `pip install -r requirements.txt` inside the venv.

### 2) Build on your platform

**macOS (DMG):**

```bash
npm run dist:mac
# outputs e.g. dist/data-assessment-tool-1.0.0-arm64.dmg
```

**Windows (NSIS installer):**

```bash
npm run dist:win
# outputs e.g. dist/data-assessment-tool Setup 1.0.0.exe
```

**Linux (AppImage/DEB/RPM):**

```bash
npm run dist:linux
```

> Code‑signing/notarization are recommended for production (see electron‑builder docs).

---

## 🧰 Common issues & fixes

* **Blank window / “Starting…” forever**

  * Check terminal logs. Ensure `app_entry.py` exists in `Contents/Resources` (packaged) or CWD (dev).
  * Make sure `waitForHttp(HEALTH_URL)` points to `/_stcore/health` and you pass `--server.port` correctly.
* **`fs is not defined`**

  * Add `const fs = require('fs')` at top of `main.js`.
* **`Address already in use`**

  * Another Streamlit process is using the port. Kill it or change `APP_PORT` env var.
* **Taxonomy/rules not found**

  * Ensure they are in `extraResources` and you pass absolute paths (`TAXONOMY_JSON`, `SKU_COVERAGE_JSON`).
* **Footer hidden behind chat input**

  * Use the “lifted” footer in `ui.py` with `lift_for_chat=True` (adds bottom offset + padding).

---

## 🔍 How the final verdict works (summary)

* Coverage/requirements load from `sku_coverage_rules.json`.
* We merge **All Verticals** rules with a vertical‑specific override (e.g., Beauty vs CnG).
* For each attribute we evaluate:

  * numeric coverage thresholds (e.g., `>= 80%`),
  * qualitative “Fails if …” conditions coming from agent issue flags,
  * AI “Missing or Unusable” flags from the detailed report.
* If any **Required** attribute fails or is unknown → **Not Eligible for GP**.
  Otherwise **Eligible for GP**.
* An LLM is prompted with the full evaluation context to write a 2–6 bullet executive summary.

---

## 📦 Releasing updates

* Bump the version:

  ```bash
  npm version patch   # or minor / major
  ```
* Build: `npm run dist:mac` (and/or `dist:win`, `dist:linux`)
* Version shown in the footer is injected at runtime via `app.getVersion()`.

---

## 🛡 Privacy & security

* Local HTTP only (`127.0.0.1`), no external listeners.
* Renderer has no Node access (`nodeIntegration: false`), uses `contextIsolation: true`.
* External links open in the OS browser; navigation to non‑local URLs is blocked.
* Do not log API keys; prefer env vars and OS keychain if you persist secrets.

---

## 🙋 Support

If you run into issues:

* Run `npm run start` from Terminal and review logs.
* Verify required resources exist under `Contents/Resources` in packaged builds.
* Check health URL in your browser: `http://127.0.0.1:8501/_stcore/health`.

---

**Happy shipping!** ✨
