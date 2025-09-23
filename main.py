import streamlit as st
from streamlit.web import bootstrap
import webview
import threading
import time
import os
import sys

# --- FIX: Updated Monkey-patch for Streamlit's signal handler ---
# This version now accepts any arguments (*args, **kwargs) that Streamlit
# might pass to it, preventing the TypeError while still disabling the
# problematic signal handler logic in a secondary thread.
bootstrap._set_up_signal_handler = lambda *args, **kwargs: None
# --- End of Fix ---

# --- Helper to get the correct path for bundled resources ---
def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- Main Application Logic ---
streamlit_app_path = get_resource_path("streamlit_app.py")
port = 8501
url = f"http://localhost:{port}"

def run_streamlit():
    """Starts the Streamlit server in a separate thread."""
    # We pass an empty list of args, and an empty dict for flag options
    bootstrap.run(streamlit_app_path, '', [], {})

def main():
    """Main function to launch the Streamlit server and the PyWebView window."""
    # Start Streamlit in a background thread
    thread = threading.Thread(target=run_streamlit)
    thread.daemon = True
    thread.start()

    # Wait a moment for the server to start
    time.sleep(5) 

    # Create and show the native window
    webview.create_window("Mx Data Assessment Tool", url, width=1280, height=800)
    webview.start()

if __name__ == "__main__":
    main()

