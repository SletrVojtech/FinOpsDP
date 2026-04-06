import urllib.parse
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from db.database import get_db_cursor
from crud import entities, metrics, costs, allocations, krr
from services.utils import humanize_memory, humanize_cpu
from services.kube_chargeback import get_daily_namespace_allocation
from services import cost_service as costs_service
from datetime import date, timedelta


import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
router = APIRouter(tags=["Web UI"])
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Default page"""
    return templates.TemplateResponse(request, "dashboard.html", {})

@router.get("/ui/scope/{node_id}", response_class=HTMLResponse)
@router.get("/ui/scope/", response_class=HTMLResponse)
def get_scope(request: Request, node_id: int = 0, cursor = Depends(get_db_cursor)):
    
    # Parse tags from the query
    active_tags = {}
    for param_name, param_value in request.query_params.items():
        if param_name.startswith("tag_") and param_value:
            clean_key = param_name[4:]
            active_tags[clean_key] = param_value

    # And reconstruct them into a future query
    current_qs = ""
    if active_tags:
        current_qs = "&" + urllib.parse.urlencode({f"tag_{k}": v for k, v in active_tags.items()})

    # Get the chain of entities and most represented tages for current scope
    chain = entities.get_chain(cursor, node_id)
    top_tags = entities.get_scoped_top_tags(cursor, node_id)
    
    # Create a stackable filter query
    items = entities.get_dynamic_items(cursor, node_id, active_tags)

    return templates.TemplateResponse(request, "partial/scope_view.html", {
        "current_scope_id": node_id,
        "chain": chain,
        "top_tags": top_tags,
        "items": items,
        "active_tags": active_tags,
        "current_qs": current_qs,
    })

@router.get("/ui/tag_values", response_class=HTMLResponse)
def get_tag_values(request: Request, scope_id: str = "", tag_key: str = None, current_qs: str = "", cursor = Depends(get_db_cursor)):
    """Generates buttons for tag values in current scope"""
    if not tag_key:
        return HTMLResponse("")
        
    try:
        scope_int = int(scope_id) if scope_id else 0
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid scope_id")
    values = entities.get_scoped_tag_values(cursor, scope_int, tag_key)
    
    return templates.TemplateResponse(request, "partial/tag_values.html", {
        "scope_id": scope_id,
        "tag_key": tag_key,
        "values": values,
        "current_qs": current_qs
    })

@router.get("/ui/metrics/{entity_id}", response_class=HTMLResponse)
def view_metrics_dashboard(request: Request, entity_id: int, current_qs: str = "",
                            scope_id: str = "", cursor = Depends(get_db_cursor)):
    """Shows a page with metrics dashboard for given entity"""
    
    available_metrics = metrics.get_available_metric_names(cursor, entity_id)
    
    # Get the resource name
    cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (entity_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity_name = row[0]

    return templates.TemplateResponse(request, "metrics_dashboard.html", {
        "entity_id": entity_id,
        "entity_name": entity_name,
        "available_metrics": available_metrics,
        "current_qs": current_qs,
        "scope_id": scope_id
    })

@router.get("/ui/chargeback", response_class=HTMLResponse)
def view_chargeback_dashboard(
    request: Request, 
    scope_id: str = "", 
    current_qs: str = "",
    cursor = Depends(get_db_cursor)
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
        "top_tags": top_tags
    })

@router.get("/ui/allocations", response_class=HTMLResponse)
def view_allocations_manager(
    request: Request, 
    cursor = Depends(get_db_cursor)
):
    """List and edit allocation rules"""
    rules = allocations.get_allocation_rules(cursor)
    return templates.TemplateResponse(request, "allocations_manager.html", {
        "rules": rules
    })


@router.get("/ui/krr")
def krr_index(request: Request, cursor = Depends(get_db_cursor)):
    """Lists all available clusters with reccomendations."""

    clusters = krr.get_krr_clusters(cursor)
    return templates.TemplateResponse(request, "krr_dashboard.html", {
        "clusters": clusters
    })


@router.get("/ui/krr/{cluster_id}")
def krr_detail(request: Request, cluster_id: int, cursor = Depends(get_db_cursor)):
    """Print out reccomendations for given cluster."""

    cluster_name = krr.get_cluster_name(cursor, cluster_id)
    raw_recommendations = krr.get_krr_recommendations_for_cluster(cursor, cluster_id)

    recommendations = []
    for row in raw_recommendations:
        clean_row = dict(row)
        
        clean_row['currentcpurequest'] = humanize_cpu(row['currentcpurequest'])
        clean_row['recommendedcpurequest'] = humanize_cpu(row['recommendedcpurequest'])
        
        clean_row['currentmemoryrequest'] = humanize_memory(row['currentmemoryrequest'])
        clean_row['recommendedmemoryrequest'] = humanize_memory(row['recommendedmemoryrequest'])
        
        recommendations.append(clean_row)

    return templates.TemplateResponse(request, "krr_report.html", {
        "cluster_name": cluster_name,
        "recommendations": recommendations
    })

@router.get("/ui/clusters")
def list_clusters(request: Request, cursor = Depends(get_db_cursor)):
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
                        target_month: str = None, cursor = Depends(get_db_cursor)):
    """Plot a stacked graph with daily costs for given cluster.
    
    Accepts an optional ?target_month=YYYY-MM query parameter.
    When called with Accept: application/json it returns only the chart data
    so the frontend can refresh the chart without a full page reload.
    """
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