"""
Metrics Web UI Router.

Serves pages and dashboard views for entity metrics, cost anomalies,
and forecast quality. All endpoints are tagged *Web UI / Metrics*.
"""

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from db.database import get_db_cursor
from crud import metrics
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["Web UI / Metrics"])

@router.get("/ui/metrics/{entity_id}", response_class=HTMLResponse)
def view_metrics_dashboard(
    request: Request, 
    entity_id: int, 
    current_qs: str = "",
    scope_id: str = "", 
    cursor=Depends(get_db_cursor)
):
    """Render the entity metrics dashboard page.

    Args:
        request (Request): Incoming HTTP request.
        entity_id (int): Entity ID whose metrics to display.
        current_qs (str): Reconstructed tag query string for links.
        scope_id (str): Current scope ID string for breadcrumb.
        cursor: Injected DB cursor.

    Returns:
        HTMLResponse: Rendered ``metrics_dashboard.html``.

    Raises:
        HTTPException: 404 if the entity is not found.
    """
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

@router.get("/ui/anomalies", response_class=HTMLResponse)
def view_anomalies_dashboard(request: Request):
    """Render the cost anomalies dashboard page.

    Args:
        request (Request): Incoming HTTP request.

    Returns:
        HTMLResponse: Rendered ``anomalies_dashboard.html``.
    """
    return templates.TemplateResponse(request, "anomalies_dashboard.html", {})

@router.get("/ui/forecast-quality", response_class=HTMLResponse)
def view_forecast_quality_dashboard(request: Request):
    """Render the forecast quality dashboard page.

    Args:
        request (Request): Incoming HTTP request.

    Returns:
        HTMLResponse: Rendered ``forecast_quality_dashboard.html``.
    """
    return templates.TemplateResponse(request, "forecast_quality_dashboard.html", {})
