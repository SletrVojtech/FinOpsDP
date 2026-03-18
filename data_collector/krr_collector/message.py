from typing import Optional, List
from pydantic import BaseModel

class KRRRecommendationPayload(BaseModel):
    cloud_provider: str
    account_id: str
    cluster_name: str
    cluster_id: str
    resource_id: str
    namespace: str
    workload_type: str
    workload_name: str
    container_name: str
    
    current_cpu_request: Optional[str] = None
    recommended_cpu_request: Optional[str] = None
    current_memory_request: Optional[str] = None
    recommended_memory_request: Optional[str] = None

class KRRBatchPayload(BaseModel):
    recommendations: List[KRRRecommendationPayload]