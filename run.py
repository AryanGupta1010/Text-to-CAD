import os
import sys
from pathlib import Path
import uvicorn

root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

if __name__ == "__main__":
    print("[*] Starting Text-to-CAD FastAPI Backend on http://localhost:8000 ...")
    app_dir = root_dir / "backend" / "app"
    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(app_dir)],
        reload_excludes=["*artifacts*", "*.step", "*.stl", "*.glb", "*.FCStd", "*.pyc"],
    )
