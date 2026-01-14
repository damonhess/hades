"""
HADES Docker Tracker - Captures container state
"""

import subprocess
import json
from typing import Optional, Dict
from datetime import datetime

class DockerTracker:
    def capture_container_state(self, container: str) -> Optional[Dict]:
        try:
            result = subprocess.run(
                ["docker", "inspect", container],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return {"exists": False, "container": container}
            inspect_data = json.loads(result.stdout)[0]
            return {
                "exists": True,
                "container": container,
                "id": inspect_data["Id"],
                "state": inspect_data["State"]["Status"],
                "running": inspect_data["State"]["Running"],
                "image": inspect_data["Config"]["Image"],
                "captured_at": datetime.now().isoformat()
            }
        except Exception as e:
            return {"exists": False, "container": container, "error": str(e)}

    def rollback_stop(self, before_state: Dict) -> Dict:
        if not before_state.get("running"):
            return {"success": True, "action": "was_not_running"}
        container = before_state["container"]
        result = subprocess.run(
            ["docker", "start", container],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return {"success": True, "action": "started", "container": container}
        return {"success": False, "error": result.stderr}

    def rollback_start(self, before_state: Dict) -> Dict:
        if before_state.get("running"):
            return {"success": True, "action": "was_running"}
        container = before_state["container"]
        result = subprocess.run(
            ["docker", "stop", container],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return {"success": True, "action": "stopped", "container": container}
        return {"success": False, "error": result.stderr}
