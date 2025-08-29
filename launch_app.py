import subprocess
import os
import sys
import socket
import logging

def find_free_port():
    """Finds and returns a free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def run_streamlit_app():
    """
    Launches the Streamlit application as a subprocess on a free port.
    The port is printed to stdout for the Electron app to capture.
    """
    port = find_free_port()
    app_path = 'streamlit_app.py' # Assumes this file is in the same directory

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info(f"Starting Streamlit app on port {port}...")

    try:
        # The `--server.headless=true` flag prevents Streamlit from
        # automatically opening a new tab in the default browser.
        process = subprocess.Popen(
            ["streamlit", "run", app_path, "--server.port", str(port), "--server.headless=true"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Communicate the port to the parent process (Electron)
        print(f"streamlit_port:{port}")
        
        # Wait for the process to finish
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            logging.error(f"Streamlit process exited with code {process.returncode}")
            logging.error(f"Streamlit stderr: {stderr}")
            sys.exit(1)
            
    except FileNotFoundError:
        logging.error("The 'streamlit' command was not found. Please ensure Streamlit is installed.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_streamlit_app()
