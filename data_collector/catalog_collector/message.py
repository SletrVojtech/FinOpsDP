from pydantic import BaseModel, confloat, constr
from typing import Optional
from pydantic import Field


class HardwareRecord(BaseModel):
    cloud: str
    instance_type: str
    instance_family: str
    vcpu: int
    memory_gb: float
    baseline_iops: Optional[int]
    baseline_throughput_mbps: Optional[float]
    network_performance: Optional[str] = None

class PricingRecord(BaseModel):
    cloud: str
    instance_type: str
    region: str
    os: str
    hourly_price_usd: float