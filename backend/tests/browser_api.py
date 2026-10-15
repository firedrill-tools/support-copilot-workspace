"""Disposable approval API for browser tests; deliberately exposes no model endpoint."""
import shutil
from pathlib import Path
import uvicorn
from support_workspace.api import create_app

root = Path(__file__).resolve().parents[2]
state = root / "frontend" / ".e2e" / "workspace.json"
state.parent.mkdir(exist_ok=True)
shutil.copyfile(root / "fixtures" / "starter.json", state)
uvicorn.run(create_app(state, include_agent=False), host="127.0.0.1", port=38123)
