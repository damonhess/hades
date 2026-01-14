"""
HADES Database Tracker - Captures row state before/after SQL operations
"""

import asyncpg
import json
import os
from typing import Optional, Dict
from datetime import datetime

# Database connection - use Docker container IP since PostgreSQL isn't exposed to host
DB_HOST = os.environ.get("HADES_DB_HOST", "172.18.0.16")
DB_USER = "supabase_admin"
DB_PASS = "i%2BNKWrdGrBsHu2n%2FLGzNMY84Avry2RhNOY2QYksldLtX7GEuxdyASrpv3n0IRinS"  # URL encoded
DEFAULT_DB_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/postgres_dev"

class DBTracker:
    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or DEFAULT_DB_URL

    async def capture_before_update(self, table: str, where_clause: str) -> Optional[Dict]:
        conn = await asyncpg.connect(self.connection_string)
        try:
            query = f"SELECT * FROM {table} WHERE {where_clause}"
            rows = await conn.fetch(query)
            return {
                "operation": "update",
                "table": table,
                "where": where_clause,
                "rows": [dict(row) for row in rows],
                "row_count": len(rows),
                "captured_at": datetime.now().isoformat()
            }
        finally:
            await conn.close()

    async def capture_before_delete(self, table: str, where_clause: str) -> Optional[Dict]:
        conn = await asyncpg.connect(self.connection_string)
        try:
            query = f"SELECT * FROM {table} WHERE {where_clause}"
            rows = await conn.fetch(query)
            return {
                "operation": "delete",
                "table": table,
                "where": where_clause,
                "rows": [dict(row) for row in rows],
                "row_count": len(rows),
                "captured_at": datetime.now().isoformat()
            }
        finally:
            await conn.close()

    async def rollback_update(self, before_state: Dict) -> Dict:
        if not before_state.get("rows"):
            return {"success": False, "error": "No rows to restore"}
        conn = await asyncpg.connect(self.connection_string)
        try:
            table = before_state["table"]
            restored = 0
            for row in before_state["rows"]:
                if "id" not in row:
                    continue
                columns = [k for k in row.keys() if k != "id"]
                set_clause = ", ".join([f"{col} = ${i+2}" for i, col in enumerate(columns)])
                values = [row["id"]] + [row[col] for col in columns]
                query = f"UPDATE {table} SET {set_clause} WHERE id = $1"
                await conn.execute(query, *values)
                restored += 1
            return {"success": True, "action": "restored", "rows_restored": restored}
        finally:
            await conn.close()

    async def rollback_delete(self, before_state: Dict) -> Dict:
        if not before_state.get("rows"):
            return {"success": False, "error": "No rows to restore"}
        conn = await asyncpg.connect(self.connection_string)
        try:
            table = before_state["table"]
            restored = 0
            for row in before_state["rows"]:
                columns = list(row.keys())
                placeholders = [f"${i+1}" for i in range(len(columns))]
                values = [row[col] for col in columns]
                query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
                await conn.execute(query, *values)
                restored += 1
            return {"success": True, "action": "reinserted", "rows_restored": restored}
        finally:
            await conn.close()
