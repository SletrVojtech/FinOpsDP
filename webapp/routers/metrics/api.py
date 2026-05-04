from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import date
from db.database import get_db_cursor
from crud import metrics, costs as cost
from .schemas import (
    AvailableMetricsResponse,
    MetricDataResponse,
    AnomaliesResponse,
    SuccessResponse,
    ForecastQualityResponse
)

router = APIRouter(prefix="/api/v1", tags=["API / Metrics"])

@router.get("/metrics/{entity_id}/available", response_model=AvailableMetricsResponse)
def api_get_available_metrics(entity_id: int, cursor=Depends(get_db_cursor)):
    """Returns names of available metrics for given entity"""
    available_metrics = metrics.get_available_metric_names(cursor, entity_id)
    return {"entity_id": entity_id, "available_metrics": available_metrics}

@router.get("/metrics/{entity_id}/data", response_model=MetricDataResponse)
def api_get_metric_data(
    entity_id: int, 
    metric_name: str, 
    time_range: str = Query("7 days", description="For instace '24 hours', '7 days', '1 month'"), 
    granularity: str = Query("1 hour", description="For instance '5 minutes', '1 hour', '1 day'"), 
    cursor=Depends(get_db_cursor)
):
    """Universal API for getting metric data."""
    data = metrics.get_metric_data(cursor, entity_id, metric_name, time_range, granularity)
    
    return {
        "status": "success",
        "entity_id": entity_id,
        "metric_name": metric_name,
        "parameters": {"time_range": time_range, "granularity": granularity},
        "data_points": data
    }

@router.get("/anomalies", response_model=AnomaliesResponse)
def api_get_anomalies(
    start_date: date = Query(default=date.today().replace(day=1), description="Start date"),
    end_date: date = Query(default=date.today(), description="End date"),
    only_unseen: bool = Query(False, description="Filter only unseen anomalies"),
    cursor=Depends(get_db_cursor)
):
    """Returns anomalies for the dashboard."""
    data = cost.get_dashboard_anomalies(cursor, start_date, end_date, only_unseen)
    return {"status": "success", "data": data}

@router.post("/anomalies/{anomaly_id}/seen", response_model=SuccessResponse)
def api_mark_anomaly_seen(anomaly_id: int, cursor=Depends(get_db_cursor)):
    """Marks an anomaly as seen."""
    cost.mark_anomaly_seen(cursor, anomaly_id)
    cursor.connection.commit()
    return {"status": "success"}

@router.get("/forecast-quality", response_model=ForecastQualityResponse)
def api_get_forecast_quality(
    target_month: str = Query(None, description="Month in YYYY-MM format"),
    cursor=Depends(get_db_cursor)
):
    """Returns forecast quality report comparing latest forecast vs actual costs."""
    if target_month:
        try:
            year, month = map(int, target_month.split('-'))
            period_date = date(year, month, 1)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid target_month, expected YYYY-MM")
    else:
        period_date = date.today().replace(day=1)

    data = cost.get_forecast_quality(cursor, period_date)
    return {"status": "success", "data": data}
