# HADES - History Aware Disaster Escape System

Rollback agent for ATLAS operations. Captures before/after state and enables undo.

## Overview

HADES is the safety net for ATLAS. When ATLAS executes an operation that goes wrong, HADES can undo it. It tracks before/after state for every operation and provides rollback capability.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         ATLAS                                │
│                    (Port 8007)                               │
└─────────────────────┬───────────────────────────────────────┘
                      │ 1. POST /api/track (before)
                      │ 2. Execute command
                      │ 3. POST /api/complete (after)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                         HADES                                │
│                    (Port 8008)                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ File Tracker │  │  DB Tracker  │  │Docker Tracker│      │
│  │  (backups)   │  │ (row state)  │  │(container)   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                          │                                   │
│                          ▼                                   │
│              ┌────────────────────────┐                     │
│              │   hades_operations     │                     │
│              │   (PostgreSQL table)   │                     │
│              └────────────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/track` | POST | Track operation before execution |
| `/api/complete` | POST | Record completion after execution |
| `/api/rollback` | POST | Roll back operation(s) |
| `/api/operations` | GET | List recent operations |

### Track Request
```json
{
  "command": "rm /tmp/test.txt",
  "operation_type": "file_delete",
  "atlas_request_id": "optional-correlation-id"
}
```

### Complete Request
```json
{
  "operation_id": "uuid-from-track",
  "success": true
}
```

### Rollback Request
```json
{
  "operation_id": "uuid-to-rollback"
}
```
Or rollback last N operations:
```json
{
  "count": 3
}
```

## CLI Usage

```bash
# List recent operations
python3 hades.py list --limit 10

# Rollback specific operation
python3 hades.py rollback --id <uuid>

# Rollback last N operations
python3 hades.py rollback-last --count 3
```

## Supported Rollback Types

| Type | Strategy | Notes |
|------|----------|-------|
| `file_write` | Restore from backup | Full file backup before modification |
| `file_delete` | Restore from backup | Backup created before deletion |
| `docker_stop` | `docker start` | Restarts stopped container |
| `docker_start` | `docker stop` | Stops started container |
| `sql_update` | Restore original values | Captures rows before UPDATE |
| `sql_delete` | Re-insert rows | Captures rows before DELETE |
| `docker_rm` | Warn only | Cannot auto-rollback |
| `sql_drop` | Warn only | Cannot auto-rollback |

## Integration with ATLAS

ATLAS calls HADES before/after every operation:

```python
# Before execution
response = requests.post("http://localhost:8008/api/track", json={
    "command": command,
    "operation_type": "file_write",
    "atlas_request_id": request_id
})
operation_id = response.json()["operation_id"]

# Execute the command
result = execute(command)

# After execution
requests.post("http://localhost:8008/api/complete", json={
    "operation_id": operation_id,
    "success": result.success
})
```

## Storage

- **File backups**: `/home/damon/hades/storage/snapshots/files/`
- **Operation history**: `hades_operations` table in `postgres_dev`

## Retention Policy

From `config/rollback_rules.yaml`:
- Max operations: 1000
- Max age: 72 hours
- Snapshot cleanup: 24 hours

## Installation

```bash
pip install --break-system-packages -r requirements.txt
```

## Running

```bash
# Direct
python3 api.py

# Via systemd
sudo cp hades-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hades-api
sudo systemctl start hades-api
```

## License

Private - Personal Use Only
