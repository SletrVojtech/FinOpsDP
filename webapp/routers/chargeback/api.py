from fastapi import APIRouter, Depends, HTTPException, Request, Query
from datetime import date, timedelta
from db.database import get_db_cursor
from services import cost_service
from services.utils import extract_active_tags
from services.kube_chargeback import get_daily_namespace_allocation
from crud import costs as cost, allocations
from .schemas import (
    ChargebackDataResponse,
    BudgetRequest,
    BudgetResponse,
    AllocationRequest,
    SuccessResponse,
    ClustersResponse,
    ClusterCostResponse
)

router = APIRouter(prefix="/api/v1", tags=["API / Chargeback"])

@router.get("/costs/chargeback", response_model=ChargebackDataResponse)
def api_get_chargeback_data(
    request: Request,
    scope_id: int = 0,
    target_month: str = None, 
    group_by_tag: str = None,
    cursor=Depends(get_db_cursor)
):
    """Returns data for current month spend and projected forecast, with optional grouping by tag."""
    active_tags = extract_active_tags(request)
    data = cost_service.get_chargeback_dashboard_data(
        cursor, scope_id, active_tags, target_month, group_by_tag
    )
    return data

@router.post("/costs/budget", response_model=BudgetResponse)
def api_set_budget(
    request: Request,
    payload: BudgetRequest,
    scope_id: int = 0, 
    target_month: str = None, 
    cursor=Depends(get_db_cursor)
):
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

@router.post("/allocations", response_model=SuccessResponse)
def api_add_allocation(request: Request, payload: AllocationRequest, cursor=Depends(get_db_cursor)):
    """Save a new allocation rule."""
    try:
        allocations.add_allocation_rule(
            cursor, payload.rule_name, payload.source_tags, payload.target_tags, payload.percentage
        )
        cursor.connection.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success"}

@router.delete("/allocations/{rule_id}", response_model=SuccessResponse)
def api_delete_allocation(request: Request, rule_id: int, cursor=Depends(get_db_cursor)):
    """Delete an allocation rule."""
    allocations.delete_allocation_rule(cursor, rule_id)
    cursor.connection.commit()
    return {"status": "success"}

@router.get("/clusters", response_model=ClustersResponse)
def api_list_clusters(cursor=Depends(get_db_cursor)):
    """List Kubernetes clusters."""
    query = "SELECT Id, ResourceName FROM Entities WHERE ResourceType = 'kubernetes_cluster' ORDER BY ResourceName"
    cursor.execute(query)
    clusters = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    return {"status": "success", "data": clusters}

@router.get("/clusters/{cluster_id}/costs", response_model=ClusterCostResponse)
def api_cluster_cost_detail(
    cluster_id: int,
    target_month: str = Query(None, description="YYYY-MM"),
    cursor=Depends(get_db_cursor)
):
    """Fetch daily cost and namespace allocation data for a cluster."""
    cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
    row = cursor.fetchone()
    cluster_name = row[0] if row else "Neznámý cluster"

    if target_month:
        try:
            year, month = map(int, target_month.split("-"))
            base_date = date(year, month, 1)
            target_month_str = target_month
        except (ValueError, TypeError, IndexError):
            raise HTTPException(status_code=422, detail="Invalid target_month, expected YYYY-MM")
    else:
        base_date = (date.today() - timedelta(days=1)).replace(day=1)
        target_month_str = base_date.strftime("%Y-%m")

    forecast_data = cost_service.calculate_chargeback_forecast(
        cursor, cluster_id, {"cluster": cluster_name}, target_month_str
    )
    daily_cluster_costs = {
        date_str: daily_cost
        for date_str, daily_cost in zip(forecast_data["labels"], forecast_data["actual_daily"])
        if daily_cost is not None
    }
    
    daily_cluster_costs = cost_service.get_aggregated_daily_costs_k8s(
        cursor, cluster_id, {"cluster": cluster_name}, 
        start_date=base_date, end_date=base_date + timedelta(days=30)
    )

    chart_data = get_daily_namespace_allocation(cursor, cluster_id, base_date, daily_cluster_costs)
    
    return {
        "status": "success",
        "chart_data": chart_data,
        "month": target_month_str
    }
