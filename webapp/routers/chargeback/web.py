from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import date, timedelta
from db.database import get_db_cursor
from crud import entities, allocations
from services import cost_service as costs_service
from services.kube_chargeback import get_daily_namespace_allocation
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["Web UI / Chargeback"])

@router.get("/ui/chargeback", response_class=HTMLResponse)
def view_chargeback_dashboard(
    request: Request, 
    scope_id: str = "", 
    target_month: str = "",
    current_qs: str = "",
    cursor=Depends(get_db_cursor)
):
    """Shows a page with chargeback dashboard"""
    try:
        scope_int = int(scope_id) if scope_id else 0
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid scope_id")
    top_tags = entities.get_scoped_top_tags(cursor, scope_int)
    
    return templates.TemplateResponse(request, "chargeback_dashboard.html", {
        "scope_id": scope_id,
        "current_qs": current_qs,
        "top_tags": top_tags,
        "target_month": target_month
    })

@router.get("/ui/allocations", response_class=HTMLResponse)
def view_allocations_manager(
    request: Request, 
    cursor=Depends(get_db_cursor)
):
    """List and edit allocation rules"""
    allocs = allocations.get_allocation_rules(cursor)
    return templates.TemplateResponse(request, "allocations_manager.html", {
        "rules": allocs
    })

@router.get("/ui/clusters", response_class=HTMLResponse)
def list_clusters(request: Request, cursor=Depends(get_db_cursor)):
    """List clusters for chargeback"""
    # Filter for clusters
    query = "SELECT Id, ResourceName FROM Entities WHERE ResourceType = 'kubernetes_cluster' ORDER BY ResourceName"
    cursor.execute(query)
    clusters = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    
    return templates.TemplateResponse(request, "clusters_dashboard.html", {
        "clusters": clusters
    })

@router.get("/ui/clusters/{cluster_id}/costs")
def cluster_cost_detail(request: Request, cluster_id: int,
                        target_month: str = None, cursor=Depends(get_db_cursor)):
    """Plot a stacked graph with daily costs for given cluster."""
    # Get cluster name
    cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
    row = cursor.fetchone()
    cluster_name = row[0] if row else "Neznámý cluster"

    # Resolve target month
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

    forecast_data = costs_service.calculate_chargeback_forecast(
        cursor, cluster_id, {"cluster": cluster_name}, target_month_str
    )
    daily_cluster_costs = {
        date_str: daily_cost
        for date_str, daily_cost in zip(forecast_data["labels"], forecast_data["actual_daily"])
        if daily_cost is not None
    }

    daily_cluster_costs = costs_service.get_aggregated_daily_costs_k8s(
        cursor, cluster_id, {"cluster": cluster_name}, 
        start_date=base_date, end_date=base_date + timedelta(days=30)
    )

    chart_data = get_daily_namespace_allocation(cursor, cluster_id, base_date, daily_cluster_costs)

    # JSON-only response for AJAX month changes
    if request.headers.get("Accept") == "application/json":
        return JSONResponse({"chart_data": chart_data, "month": target_month_str})

    return templates.TemplateResponse(request, "cluster_daily.html", {
        "cluster_name": cluster_name,
        "cluster_id": cluster_id,
        "chart_data": chart_data,
        "month": target_month_str
    })
