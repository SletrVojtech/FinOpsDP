"""
Cost Message Module.

This module defines the data structures used for passing cost information
from the cost collector to the ingestion queue.
"""

from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

class CostPayload(BaseModel):
    """
    Represents a single cost record matching the FOCUS 1.2 specification format.
    """
    # Entity identification
    provider: str
    billing_id: str
    billing_name: str
    account_id: str
    account_name: str
    region_id: str
    resource_id: str
    resource_name: str
    resource_type: str
    tags: Dict[str, str] = Field(default_factory=dict)

    # Cost entry identification
    service_name: str
    service_category: str
    sku_price_id: str
    
    # Charge period
    charge_period_start: datetime
    charge_period_end: datetime
    
    # Costs
    billed_cost: float
    billing_currency: str

    

class CostBatchPayload(BaseModel):
    """
    Batch Message for RabbitMQ.
    """
    records: List[CostPayload]