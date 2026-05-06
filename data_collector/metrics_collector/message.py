"""
Metrics Message Module.

This module defines the Pydantic model for multi-cloud resource metrics
collected from AWS CloudWatch and Azure Monitor.
"""

from pydantic import BaseModel
from typing import Any, Dict, List

class MetricsPayload(BaseModel):
    """
    Represents a normalized metric payload for a specific cloud resource.
    """
    provider: str
    resource_id: str
    resource_type: str
    resource_name: str
    metric_name: str
    metric_period: int
    billing_account_id: str
    region_name: str
    tags: Dict[str, str]
    datapoints: List[Dict[str, Any]]
    extras: Dict[str, Any]

