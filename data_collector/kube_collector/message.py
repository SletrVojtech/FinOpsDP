from pydantic import BaseModel, Field
from typing import Dict, List

class Datapoint(BaseModel):
    timestamp: float 
    value: float

class KubeMetricsPayload(BaseModel):

    cloud_provider: str
    account_id: str

    resource_id: str
    resource_name: str
    resource_type: str = "kubernetes_namespace"
    
    metric_name: str
    metric_period: int = 60 
    tags: Dict[str, str] = Field(default_factory=dict)
    datapoints: List[Datapoint]