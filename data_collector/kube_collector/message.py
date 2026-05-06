"""
Kubernetes Metrics Message Module.

This module defines the Pydantic models for Kubernetes namespace-level
metrics collected from Prometheus.
"""

from pydantic import BaseModel, Field
from typing import Dict, List

class Datapoint(BaseModel):
    """
    Represents a single metric value at a specific point in time.
    """
    timestamp: float 
    value: float

class KubeMetricsPayload(BaseModel):
    """
    Represents a set of metrics for a Kubernetes resource.
    """
    cloud_provider: str
    account_id: str

    resource_id: str
    resource_name: str
    resource_type: str = "kubernetes_namespace"
    
    metric_name: str
    metric_period: int = 60 
    tags: Dict[str, str] = Field(default_factory=dict)
    datapoints: List[Datapoint]