"""
Chargeback REST API Router.

Exposes JSON endpoints for chargeback data, cost budgets, allocation
rules, and cluster cost details. All endpoints are prefixed
``/api/v1`` and tagged *API / Chargeback*.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from datetime import date, timedelta
from db.database import get_db_cursor
from services.chargeback.dashboard import get_chargeback_dashboard_data, calculate_chargeback_forecast
from services.chargeback.aggregation import get_aggregated_daily_costs_k8s
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
    """Return current-month spend and projected forecast, optionally grouped by tag.

    Args:
        request (Request): Incoming request (provides tag headers/query params).
        scope_id (int): Entity scope ID. Defaults to 0 (global).
        target_month (str, optional): Target month in ``YYYY-MM`` format.
        group_by_tag (str, optional): Tag key to group the cost breakdown by.
        cursor: Injected DB cursor.

    Returns:
        ChargebackDataResponse: Dashboard payload.
    """
    active_tags = extract_active_tags(request)
    data = get_chargeback_dashboard_data(
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
    """Save or update the monthly budget for the given scope and tags.

    Args:
        request (Request): Incoming request (provides tag headers/query params).
        payload (BudgetRequest): Request body containing ``amount``.
        scope_id (int): Entity scope ID. Defaults to 0.
        target_month (str, optional): Target month in ``YYYY-MM`` format.
            Defaults to the current calendar month.
        cursor: Injected DB cursor.

    Returns:
        BudgetResponse: Confirmation with the saved amount.

    Raises:
        HTTPException: 422 if ``target_month`` is not a valid ``YYYY-MM`` string.
    """
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
    """Create a new cost allocation rule.

    Args:
        request (Request): Incoming HTTP request.
        payload (AllocationRequest): Rule definition with source/target
            tags and percentage.
        cursor: Injected DB cursor.

    Returns:
        SuccessResponse: ``{"status": "success"}``.

    Raises:
        HTTPException: 400 if the source tag set would exceed 100 %.
    """
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
    """Delete an existing allocation rule by ID.

    Args:
        request (Request): Incoming HTTP request.
        rule_id (int): Primary key of the rule to delete.
        cursor: Injected DB cursor.

    Returns:
        SuccessResponse: ``{"status": "success"}``.
    """
    allocations.delete_allocation_rule(cursor, rule_id)
    cursor.connection.commit()
    return {"status": "success"}

@router.get("/clusters", response_model=ClustersResponse)
def api_list_clusters(cursor=Depends(get_db_cursor)):
    """List all Kubernetes clusters registered in the system.

    Args:
        cursor: Injected DB cursor.

    Returns:
        ClustersResponse: List of ``{id, name}`` cluster dicts.
    """
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
    """Return daily cost and namespace allocation breakdown for a cluster.

    Args:
        cluster_id (int): Entity ID of the cluster.
        target_month (str, optional): Target month in ``YYYY-MM`` format.
            Defaults to the month before today.
        cursor: Injected DB cursor.

    Returns:
        ClusterCostResponse: Chart data and month string.

    Raises:
        HTTPException: 422 if ``target_month`` is invalid.
    """
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

    forecast_data = calculate_chargeback_forecast(
        cursor, cluster_id, {"cluster": cluster_name}, target_month_str
    )
    daily_cluster_costs = {
        date_str: daily_cost
        for date_str, daily_cost in zip(forecast_data["labels"], forecast_data["actual_daily"])
        if daily_cost is not None
    }
    
    daily_cluster_costs = get_aggregated_daily_costs_k8s(
        cursor, cluster_id, {"cluster": cluster_name}, 
        start_date=base_date, end_date=base_date + timedelta(days=30)
    )

    chart_data = get_daily_namespace_allocation(cursor, cluster_id, base_date, daily_cluster_costs)
    
    return {
        "status": "success",
        "chart_data": chart_data,
        "month": target_month_str
    }
