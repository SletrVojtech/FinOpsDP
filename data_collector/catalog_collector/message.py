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
    # Instance class constraints
    architecture: str = 'x86_64'               # 'x86_64' or 'arm64'
    is_gpu: bool = False
    is_confidential: bool = False               # Confidential Computing
    has_local_storage: bool = False             # Local NVMe / SSD
    supports_premium_storage: bool = False      # Premium IO

class PricingRecord(BaseModel):
    cloud: str
    instance_type: str
    region: str
    os: str
    hourly_price_usd: float