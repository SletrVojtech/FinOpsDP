from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class AnomalyEntry(BaseModel):
    date: str
    is_anomaly: bool
    actual: Optional[float]
    threshold: Optional[float]
    delta: float
    type: Optional[str] = None

class ChargebackDataResponse(BaseModel):
    month: str
    projected_total: Optional[float]
    labels: List[str]
    actual_daily: List[Optional[float]]
    actual_cumulative: List[Optional[float]]
    forecast_cumulative: List[Optional[float]]
    anomalies: List[AnomalyEntry]
    budget: Optional[float]
    breakdown_by_category: Dict[str, List[Optional[float]]]

class BudgetRequest(BaseModel):
    amount: float

class BudgetResponse(BaseModel):
    status: str
    amount: float

class AllocationRequest(BaseModel):
    rule_name: str
    source_tags: Dict[str, str]
    target_tags: Dict[str, str]
    percentage: float

class SuccessResponse(BaseModel):
    status: str

class ClusterEntity(BaseModel):
    id: int
    name: str

class ClustersResponse(BaseModel):
    status: str
    data: List[ClusterEntity]

class DatasetEntry(BaseModel):
    label: str
    data: List[float]

class ClusterCostChartData(BaseModel):
    labels: List[str]
    datasets: List[DatasetEntry]

class ClusterCostResponse(BaseModel):
    status: str
    chart_data: ClusterCostChartData
    month: str
