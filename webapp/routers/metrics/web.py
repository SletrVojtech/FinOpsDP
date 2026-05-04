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

@router.get("/ui/anomalies", response_class=HTMLResponse)
def view_anomalies_dashboard(request: Request):
    """Shows a page with the anomalies dashboard."""
    return templates.TemplateResponse(request, "anomalies_dashboard.html", {})

@router.get("/ui/forecast-quality", response_class=HTMLResponse)
def view_forecast_quality_dashboard(request: Request):
    """Shows a page with the forecast quality dashboard."""
    return templates.TemplateResponse(request, "forecast_quality_dashboard.html", {})
