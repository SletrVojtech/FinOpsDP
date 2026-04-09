from fastapi import APIRouter, Depends, Query, Request, HTTPException, APIRouter, Depends
from services import cost_service
from services.utils import extract_active_tags
from datetime import date
from pydantic import BaseModel
from services import downsizing as downsizing_service
from typing import List
import crud.costs as cost
from crud import allocations, entities, metrics, downsizing_rules
from db.database import get_db_cursor




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
        try:
            year, month = map(int, target_month.split('-'))
            period_date = date(year, month, 1)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid target_month, expected YYYY-MM")
    else:
        period_date = date.today().replace(day=1)

    cost.set_budget(cursor, scope_id, active_tags, period_date, payload.amount)
    cursor.connection.commit()
    
    return {"status": "success", "amount": payload.amount}

@router.post("/allocations")
def api_add_allocation(request: Request, payload: allocations.AllocationRequest, cursor = Depends(get_db_cursor)):
    """Save a new allocation rule."""
    try:
        allocations.add_allocation_rule(
            cursor, payload.rule_name, payload.source_tags, payload.target_tags, payload.percentage
        )
        cursor.connection.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success"}

@router.delete("/allocations/{rule_id}")
def api_delete_allocation(request: Request, rule_id: int, cursor = Depends(get_db_cursor)):
    """Delete an allocation rule."""
    allocations.delete_allocation_rule(cursor, rule_id)
    cursor.connection.commit()
    return {"status": "success"}

class DownsizingRulesRequest(BaseModel):
    excluded_patterns: List[str]

@router.post("/downsizing-rules")
def api_set_downsizing_rules(
    request: Request,
    payload: DownsizingRulesRequest,
    scope_id: int = 0,
    cursor = Depends(get_db_cursor)
):
    """Set downsizing rules for the current scope and tags."""
    active_tags = extract_active_tags(request)
    downsizing_rules.set_excluded_patterns(cursor, scope_id, active_tags, payload.excluded_patterns)
    cursor.connection.commit()
    return {"status": "success"}

@router.get("/downsizing-rules")
def api_get_downsizing_rules(
    request: Request,
    scope_id: int = 0,
    cursor = Depends(get_db_cursor)
):
    """Get downsizing rules for the current scope and tags."""
    active_tags = extract_active_tags(request)
    patterns = downsizing_rules.get_exact_excluded_patterns(cursor, scope_id, active_tags)
    return {"status": "success", "excluded_patterns": patterns}

@router.get("/downsizing/{entity_id}")
def get_downsizing_recommendation(
    request: Request,
    entity_id: int,
    scope_id: int = Query(0, description="Scope ID pro filtrování pravidel"),
    analysis_days: int = Query(30, description="Počet dní pro analýzu"),
    target_cpu: float = Query(60.0, description="Cílové zatížení CPU v %"),
    target_ram: float = Query(80.0, description="Cílové zatížení RAM v %"),
    cursor = Depends(get_db_cursor)
):
    """
    Returns a reccomendation for downsizing given instance.
    """
    # Fetch entity tags
    cursor.execute("SELECT Tags FROM Entities WHERE Id = %(entity_id)s", {"entity_id": entity_id})
    row = cursor.fetchone()
    entity_tags = row[0] if row and row[0] else {}

    auto_excluded = downsizing_rules.get_entity_excluded_patterns(cursor, scope_id, entity_tags)

    result = downsizing_service.evaluate_downsizing(
        db_cursor=cursor,
        resource_id=entity_id,
        analysis_days=analysis_days,
        target_cpu_util=target_cpu,
        target_ram_util=target_ram,
        excluded_filters=auto_excluded
    )
    
    return result

@router.get("/anomalies")
def api_get_anomalies(
    start_date: date = Query(default=date.today().replace(day=1), description="Start date"),
    end_date: date = Query(default=date.today(), description="End date"),
    only_unseen: bool = Query(False, description="Filter only unseen anomalies"),
    cursor = Depends(get_db_cursor)
):
    """Returns anomalies for the dashboard."""
    data = cost.get_dashboard_anomalies(cursor, start_date, end_date, only_unseen)
    return {"status": "success", "data": data}

@router.post("/anomalies/{anomaly_id}/seen")
def api_mark_anomaly_seen(anomaly_id: int, cursor = Depends(get_db_cursor)):
    """Marks an anomaly as seen."""
    cost.mark_anomaly_seen(cursor, anomaly_id)
    cursor.connection.commit()
    return {"status": "success"}