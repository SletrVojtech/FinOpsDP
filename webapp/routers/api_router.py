from fastapi import APIRouter, Depends
from db.database import get_db_cursor
from crud import entities, metrics
from fastapi import Query


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

@router.get("/metrics/{entity_id}/available")
def api_get_available_metrics(entity_id: int, cursor = Depends(get_db_cursor)):
    """Returns names of available metrics for given entity"""
    available_metrics = metrics.get_available_metric_names(cursor, entity_id)
    return {"entity_id": entity_id, "available_metrics": available_metrics}

@router.get("/metrics/{entity_id}/data")
def api_get_metric_data(entity_id: int, metric_name: str, 
    time_range: str = Query("7 days", description="For instace '24 hours', '7 days', '1 month'"), 
    granularity: str = Query("1 hour", description="For instance '5 minutes', '1 hour', '1 day'"), 
    cursor = Depends(get_db_cursor)
):
    """
    Universal API for getting metric data.
    """
    data = metrics.get_metric_data(cursor, entity_id, metric_name, time_range, granularity)
    
    return {
        "status": "success",
        "entity_id": entity_id,
        "metric_name": metric_name,
        "parameters": {"time_range": time_range, "granularity": granularity},
        "data_points": data
    }