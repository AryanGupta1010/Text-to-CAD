import os
import sys
from pathlib import Path
import uvicorn

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

if __name__ == "__main__":
    print("[*] Starting Text-to-CAD FastAPI Backend on http://localhost:8000 ...")
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
