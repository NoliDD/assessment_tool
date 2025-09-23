# app_entry.py — minimal launcher for a frozen/bundled app
# app_entry.py — robust launcher for a packaged Streamlit app
import os
import sys
from pathlib import Path
from streamlit import config as _config
from streamlit.web import bootstrap


def _pick_port(default: int) -> int:
    """Read port from env (STREAMLIT_SERVER_PORT) with sane fallback."""
    try:
        return int(os.getenv("STREAMLIT_SERVER_PORT", str(default)))
    except ValueError:
        return default


def _run_streamlit(script_path: Path, port: int) -> None:
    """Run Streamlit in-headless mode, compatible with multiple Streamlit versions.

    Newer Streamlit (≥1.30):
        bootstrap.run(file, args=[], flag_options={}, is_hello=False)
    Older Streamlit:
        bootstrap.run(file, command_line, args, flag_options)
    """
    # Ensure CWD is the app directory so relative file loads (yaml/json/csv) work
    os.chdir(str(script_path.parent))

    # Pass options both via flag_options and config for broader compatibility
    flag_options = {
        "server.port": port,
        "server.headless": True,
        "server.address": "127.0.0.1",
    }
    _config.set_option("server.headless", True)
    _config.set_option("server.port", port)
    _config.set_option("server.address", "127.0.0.1")

    try:
        # Streamlit ≥1.30 (undocumented internal API, but widely used)
        bootstrap.run(str(script_path), args=[], flag_options=flag_options, is_hello=False)
    except TypeError:
        # Older Streamlit fallback
        bootstrap.run(str(script_path), "", [], flag_options)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    script_path = base_dir / "streamlit_app.py"
    if not script_path.exists():
        sys.stderr.write(f"ERROR: Streamlit app not found: {script_path}\n")
        sys.exit(2)

    port = _pick_port(8501)
    _run_streamlit(script_path, port)


if __name__ == "__main__":
    main()