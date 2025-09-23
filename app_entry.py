# app_entry.py — minimal launcher for a frozen/bundled app
import os
from streamlit.web import bootstrap

def main():
    # point to your real Streamlit app script
    script_path = os.path.join(os.path.dirname(__file__), "streamlit_app.py")

    # let Electron control the port; default to 8501
    port = int(os.getenv("STREAMLIT_SERVER_PORT", "8501"))
    args = [f"--server.port={port}", "--server.headless=true", script_path]

    # launch exactly like `streamlit run streamlit_app.py --server.port=...`
    bootstrap.run(script_path, "", args, {})

if __name__ == "__main__":
    main()
