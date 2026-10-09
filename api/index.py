import sys
from pathlib import Path

# Add current api directory and backend directory to sys.path so app modules can be resolved
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parent
backend_dir = repo_root / "backend"

if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.main import app, init_resources, data_store, agent

# Initialize data store and agent eagerly for serverless invocations
try:
    init_resources()
except Exception as e:
    pass
