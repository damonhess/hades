#!/usr/bin/env python3
"""
HADES - History Aware Disaster Escape System
Rollback agent for ATLAS operations
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
import asyncpg
import yaml

# Database connection - use Docker container IP since PostgreSQL isn't exposed to host
DB_HOST = os.environ.get("HADES_DB_HOST", "172.18.0.16")
DB_USER = "supabase_admin"
DB_PASS = "i%2BNKWrdGrBsHu2n%2FLGzNMY84Avry2RhNOY2QYksldLtX7GEuxdyASrpv3n0IRinS"  # URL encoded
DB_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/postgres_dev"

from trackers.file_tracker import FileTracker
from trackers.db_tracker import DBTracker
from trackers.docker_tracker import DockerTracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('HADES')

class HADES:
    def __init__(self):
        self.file_tracker = FileTracker()
        self.db_tracker = DBTracker()
        self.docker_tracker = DockerTracker()
        self.db_connection = None
        config_path = Path(__file__).parent / "config" / "rollback_rules.yaml"
        with open(config_path) as f:
            self.rules = yaml.safe_load(f)

    async def initialize(self):
        self.db_connection = await asyncpg.connect(DB_URL)
        logger.info(f"HADES initialized (DB: {DB_HOST})")

    async def track_operation(self, command: str, operation_type: str, atlas_request_id: str = None) -> str:
        before_state = await self._capture_before_state(command, operation_type)
        op_id = await self.db_connection.fetchval("""
            INSERT INTO hades_operations
            (atlas_request_id, operation_type, command, before_state)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, atlas_request_id, operation_type, command, json.dumps(before_state))
        logger.info(f"Tracking operation {op_id}: {operation_type}")
        return str(op_id)

    async def complete_operation(self, operation_id: str, success: bool) -> None:
        row = await self.db_connection.fetchrow(
            "SELECT * FROM hades_operations WHERE id = $1", operation_id
        )
        if not row:
            logger.warning(f"Operation {operation_id} not found")
            return
        after_state = await self._capture_after_state(row['command'], row['operation_type'])
        rollback_cmd = self._generate_rollback_command(row['operation_type'], row['command'])
        await self.db_connection.execute("""
            UPDATE hades_operations
            SET after_state = $1, rollback_command = $2
            WHERE id = $3
        """, json.dumps(after_state), rollback_cmd, operation_id)

    async def rollback(self, operation_id: str) -> Dict:
        row = await self.db_connection.fetchrow(
            "SELECT * FROM hades_operations WHERE id = $1", operation_id
        )
        if not row:
            return {"success": False, "error": "Operation not found"}
        if row['rolled_back']:
            return {"success": False, "error": "Already rolled back"}
        before_state = json.loads(row['before_state']) if row['before_state'] else {}
        operation_type = row['operation_type']
        result = await self._execute_rollback(operation_type, before_state)
        if result.get("success"):
            await self.db_connection.execute("""
                UPDATE hades_operations
                SET rolled_back = TRUE, rolled_back_at = NOW()
                WHERE id = $1
            """, operation_id)
        return result

    async def rollback_last(self, count: int = 1) -> list:
        rows = await self.db_connection.fetch("""
            SELECT id FROM hades_operations
            WHERE NOT rolled_back
            ORDER BY executed_at DESC
            LIMIT $1
        """, count)
        results = []
        for row in rows:
            result = await self.rollback(str(row['id']))
            results.append({"id": str(row['id']), **result})
        return results

    async def get_recent_operations(self, limit: int = 10) -> list:
        rows = await self.db_connection.fetch("""
            SELECT id, operation_type, command, executed_at, rolled_back
            FROM hades_operations
            ORDER BY executed_at DESC
            LIMIT $1
        """, limit)
        return [dict(row) for row in rows]

    async def _capture_before_state(self, command: str, operation_type: str) -> Dict:
        if operation_type.startswith("file_"):
            filepath = self._extract_filepath(command)
            if filepath:
                return self.file_tracker.capture_before(filepath)
        elif operation_type.startswith("docker_"):
            container = self._extract_container(command)
            if container:
                return self.docker_tracker.capture_container_state(container)
        elif operation_type.startswith("sql_"):
            parsed = self._parse_sql(command)
            if parsed and operation_type in ["sql_update", "sql_delete"]:
                if operation_type == "sql_update":
                    return await self.db_tracker.capture_before_update(parsed["table"], parsed.get("where", "1=1"))
                else:
                    return await self.db_tracker.capture_before_delete(parsed["table"], parsed.get("where", "1=1"))
        return {"captured": False, "reason": "Unknown operation type"}

    async def _capture_after_state(self, command: str, operation_type: str) -> Dict:
        if operation_type.startswith("file_"):
            filepath = self._extract_filepath(command)
            if filepath:
                return self.file_tracker.capture_after(filepath)
        return {"captured": False}

    async def _execute_rollback(self, operation_type: str, before_state: Dict) -> Dict:
        if operation_type.startswith("file_"):
            return self.file_tracker.rollback(before_state)
        elif operation_type == "docker_stop":
            return self.docker_tracker.rollback_stop(before_state)
        elif operation_type == "docker_start":
            return self.docker_tracker.rollback_start(before_state)
        elif operation_type == "sql_update":
            return await self.db_tracker.rollback_update(before_state)
        elif operation_type == "sql_delete":
            return await self.db_tracker.rollback_delete(before_state)
        return {"success": False, "error": f"No rollback strategy for {operation_type}"}

    def _generate_rollback_command(self, operation_type: str, command: str) -> str:
        strategy = self.rules.get("rollback_strategies", {}).get(operation_type, {})
        template = strategy.get("rollback_template")
        if template:
            if operation_type == "docker_stop":
                container = self._extract_container(command)
                return template.format(container=container)
        return "Manual rollback required"

    def _extract_filepath(self, command: str) -> Optional[str]:
        patterns = [r'>\s*(\S+)', r'cp\s+\S+\s+(\S+)', r'mv\s+\S+\s+(\S+)', r'rm\s+(-\w+\s+)?(\S+)']
        for pattern in patterns:
            match = re.search(pattern, command)
            if match:
                return match.group(match.lastindex)
        return None

    def _extract_container(self, command: str) -> Optional[str]:
        match = re.search(r'docker\s+\w+\s+(\S+)', command)
        return match.group(1) if match else None

    def _parse_sql(self, command: str) -> Optional[Dict]:
        update_match = re.search(r'UPDATE\s+(\w+)\s+SET.*?WHERE\s+(.+?)(?:;|$)', command, re.IGNORECASE)
        if update_match:
            return {"table": update_match.group(1), "where": update_match.group(2)}
        delete_match = re.search(r'DELETE\s+FROM\s+(\w+)\s+WHERE\s+(.+?)(?:;|$)', command, re.IGNORECASE)
        if delete_match:
            return {"table": delete_match.group(1), "where": delete_match.group(2)}
        return None


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='HADES - Rollback Agent')
    parser.add_argument('command', choices=['list', 'rollback', 'rollback-last'])
    parser.add_argument('--id', help='Operation ID to rollback')
    parser.add_argument('--count', type=int, default=1, help='Number of operations to rollback')
    parser.add_argument('--limit', type=int, default=10, help='Number of operations to list')
    args = parser.parse_args()

    hades = HADES()
    await hades.initialize()

    if args.command == 'list':
        ops = await hades.get_recent_operations(args.limit)
        for op in ops:
            status = "ROLLED BACK" if op['rolled_back'] else "ACTIVE"
            print(f"{op['id']} | {op['operation_type']} | {op['command'][:50]} | {status}")
    elif args.command == 'rollback':
        if not args.id:
            print("Error: --id required")
            return
        result = await hades.rollback(args.id)
        print(json.dumps(result, indent=2))
    elif args.command == 'rollback-last':
        results = await hades.rollback_last(args.count)
        print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
