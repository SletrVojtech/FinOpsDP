from fastapi import APIRouter, Depends
from db.database import get_db_cursor
from crud import entities, metrics
from fastapi import Query, Request
from services import cost_service
from services.utils import extract_active_tags
from datetime import date
from pydantic import BaseModel
from services import downsizing as downsizing_service
from typing import List
from services.utils import extract_active_tags
import crud.costs as cost
from crud import allocations




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

@router.get("/costs/chargeback")
def api_get_chargeback_data(
    request: Request,
    scope_id: int = 0,
    target_month: str = None, 
    group_by_tag: str = None,
    cursor = Depends(get_db_cursor)
):
    """Returns data for current month spend and projected forecast, with optional grouping by tag."""
    
    active_tags = extract_active_tags(request)
    
    data = cost_service.get_chargeback_dashboard_data(
        cursor, scope_id, active_tags, target_month, group_by_tag
    )
    
    return data



class BudgetRequest(BaseModel):
    amount: float

@router.post("/costs/budget")
def api_set_budget(request: Request,payload: BudgetRequest,scope_id: int = 0, 
    target_month: str = None, cursor = Depends(get_db_cursor)):
    """Save new budget for given scope and tags."""
    active_tags = extract_active_tags(request)
    
    if target_month:
        year, month = map(int, target_month.split('-'))
        period_date = date(year, month, 1)
    else:
        period_date = date.today().replace(day=1)

    cost.set_budget(cursor, scope_id, active_tags, period_date, payload.amount)
    cursor.connection.commit()
    
    return {"status": "success", "amount": payload.amount}

@router.post("/allocations")
def api_add_allocation(request: Request, payload: allocations.AllocationRequest, cursor = Depends(get_db_cursor)):
    """Save a new allocation rule."""
    allocations.add_allocation_rule(
        cursor, payload.rule_name, payload.source_tags, payload.target_tags, payload.percentage
    )
    cursor.connection.commit()
    return {"status": "success"}

@router.delete("/allocations/{rule_id}")
def api_delete_allocation(request: Request, rule_id: int, cursor = Depends(get_db_cursor)):
    """Delete an allocation rule."""
    allocations.delete_allocation_rule(cursor, rule_id)
    cursor.connection.commit()
    return {"status": "success"}

@router.get("/downsizing/{entity_id}")
def get_downsizing_recommendation(
    entity_id: int,
    analysis_days: int = Query(30, description="Počet dní pro analýzu"),
    target_cpu: float = Query(60.0, description="Cílové zatížení CPU v %"),
    target_ram: float = Query(80.0, description="Cílové zatížení RAM v %"),
    excluded_filters: List[str] = Query(default=[], description="Filtry instancí k vyloučení"),
    cursor = Depends(get_db_cursor)
):
    """
    Returns a reccomendation for downsizing given instance.
    """
    result = downsizing_service.evaluate_downsizing(
        db_cursor=cursor,
        resource_id=entity_id,
        analysis_days=analysis_days,
        target_cpu_util=target_cpu,
        target_ram_util=target_ram,
        excluded_filters=excluded_filters
    )
    
    return result