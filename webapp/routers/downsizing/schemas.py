from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class DownsizingRulesRequest(BaseModel):
    excluded_patterns: List[str]

class DownsizingRulesResponse(BaseModel):
    status: str
    excluded_patterns: List[str]

class SuccessResponse(BaseModel):
    status: str

class DownsizingFinancials(BaseModel):
    projected_daily_cost_eur: float
    estimated_monthly_savings_eur: float
    savings_percentage: float

class DownsizingRecommendation(BaseModel):
    recommended_instance: str
    warnings: List[str]
    financials: Optional[DownsizingFinancials] = None

class DownsizingTelemetry(BaseModel):
    cpu_p95: Optional[float]
    ram_max: Optional[float]
    target_vcpu: float
    target_ram: float

class DownsizingResponse(BaseModel):
    status: str
    action: Optional[str] = None
    message: Optional[str] = None
    current_instance: Optional[str] = None
    recommendations: Optional[List[DownsizingRecommendation]] = None
    constraints_applied: Optional[Dict[str, Any]] = None
    warning: Optional[str] = None
    current_actual_daily_cost_eur: Optional[float] = None
    telemetry_used: Optional[DownsizingTelemetry] = None
