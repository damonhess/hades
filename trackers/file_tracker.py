"""
HADES File Tracker - Captures file state before/after operations
"""

import os
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

SNAPSHOT_DIR = Path("/home/damon/hades/storage/snapshots/files")

class FileTracker:
    def __init__(self):
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def capture_before(self, filepath: str) -> Optional[Dict]:
        path = Path(filepath)
        if not path.exists():
            return {"exists": False, "path": filepath}
        stat = path.stat()
        content_hash = self._hash_file(path)
        backup_path = self._create_backup(path)
        return {
            "exists": True,
            "path": filepath,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "content_hash": content_hash,
            "backup_path": str(backup_path),
            "captured_at": datetime.now().isoformat()
        }

    def capture_after(self, filepath: str) -> Optional[Dict]:
        path = Path(filepath)
        if not path.exists():
            return {"exists": False, "path": filepath}
        stat = path.stat()
        content_hash = self._hash_file(path)
        return {
            "exists": True,
            "path": filepath,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "content_hash": content_hash,
            "captured_at": datetime.now().isoformat()
        }

    def rollback(self, before_state: Dict) -> Dict:
        filepath = before_state["path"]
        if not before_state["exists"]:
            path = Path(filepath)
            if path.exists():
                path.unlink()
                return {"success": True, "action": "deleted", "path": filepath}
            return {"success": True, "action": "already_gone", "path": filepath}
        backup_path = before_state.get("backup_path")
        if not backup_path or not Path(backup_path).exists():
            return {"success": False, "error": "Backup not found", "path": filepath}
        shutil.copy2(backup_path, filepath)
        return {"success": True, "action": "restored", "path": filepath}

    def _hash_file(self, path: Path) -> str:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _create_backup(self, path: Path) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{path.name}.{timestamp}.bak"
        backup_path = SNAPSHOT_DIR / backup_name
        shutil.copy2(path, backup_path)
        return backup_path
