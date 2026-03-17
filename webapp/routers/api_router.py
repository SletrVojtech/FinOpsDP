from fastapi import APIRouter, Depends
from db.database import get_db_cursor
from crud import entities


# This router will have all paths with "/api/v1" prefix
router = APIRouter(prefix="/api/v1", tags=["API"])

@router.get("/roots")
def api_get_roots(cursor = Depends(get_db_cursor)):
    """Returns roots of the hierarchy."""
    data = entities.get_roots(cursor)
    return {"status": "success", "data": data}

@router.get("/children/{parent_id}")
def api_get_children(parent_id: int, cursor = Depends(get_db_cursor)):
    """Returns children of given Id"""
    data = entities.get_children(cursor, parent_id)
    return {"status": "success", "data": data}