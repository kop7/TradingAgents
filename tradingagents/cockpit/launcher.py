"""Launch the optional UI without importing Streamlit during CLI discovery."""

import importlib.util
import subprocess
import sys
from pathlib import Path


def launch():
    if importlib.util.find_spec("streamlit") is None:
        raise RuntimeError('Instaliraj UI ovisnosti: pip install ".[cockpit]"')
    return subprocess.call([
        sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("app.py")),
        "--server.address=127.0.0.1", "--server.port=8501",
        "--browser.gatherUsageStats=false",
    ])
