#!/usr/bin/env python3
"""
HADES API - Called by ATLAS for operation tracking
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hades import HADES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('HADES-API')

app = FastAPI(title="HADES API", version="1.0.0")
hades_instance = None


class TrackRequest(BaseModel):
    command: str
    operation_type: str
    atlas_request_id: Optional[str] = None


class CompleteRequest(BaseModel):
    operation_id: str
    success: bool


class RollbackRequest(BaseModel):
    operation_id: Optional[str] = None
    count: Optional[int] = 1


@app.on_event("startup")
async def startup():
    global hades_instance
    hades_instance = HADES()
    await hades_instance.initialize()
    logger.info("HADES API started")


@app.post("/api/track")
async def track(req: TrackRequest):
    op_id = await hades_instance.track_operation(req.command, req.operation_type, req.atlas_request_id)
    return {"operation_id": op_id}


@app.post("/api/complete")
async def complete(req: CompleteRequest):
    await hades_instance.complete_operation(req.operation_id, req.success)
    return {"status": "recorded"}


@app.post("/api/rollback")
async def rollback(req: RollbackRequest):
    if req.operation_id:
        result = await hades_instance.rollback(req.operation_id)
    else:
        result = await hades_instance.rollback_last(req.count)
    return result


@app.get("/api/operations")
async def list_operations(limit: int = 10):
    return await hades_instance.get_recent_operations(limit)


@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "hades-api"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
