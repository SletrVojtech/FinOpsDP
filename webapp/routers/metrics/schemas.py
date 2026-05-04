from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class AvailableMetricsResponse(BaseModel):
    entity_id: int
    available_metrics: List[str]

class MetricDataPoint(BaseModel):
    time: Optional[str]
    avg: float
    max: float
    min: float
    sum: float
    count: int

class MetricDataResponse(BaseModel):
    status: str
    entity_id: int
    metric_name: str
    parameters: Dict[str, str]
    data_points: List[MetricDataPoint]

class DashboardAnomaly(BaseModel):
    id: int
    scope_id: Optional[int]
    scope_name: str
    tags: Optional[Dict[str, str]]
    date: str
    type: str
    actual: Optional[float]
    predicted: Optional[float]
    threshold: Optional[float]
    delta: Optional[float]
    is_seen: bool
    detected_at: Optional[str]

class AnomaliesResponse(BaseModel):
    status: str
    data: List[DashboardAnomaly]

class ForecastQualityEntry(BaseModel):
    scope_id: Optional[int]
    scope_name: str
    tags: Optional[Dict[str, str]]
    forecast_date: Optional[str]
    projected_amount: float
    actual_amount: float
    variance: float
    accuracy: float
    daily_forecasts: Dict[str, float]
    daily_actuals: Dict[str, float]

class ForecastQualityResponse(BaseModel):
    status: str
    data: List[ForecastQualityEntry]

class SuccessResponse(BaseModel):
    status: str
