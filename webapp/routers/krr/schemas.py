from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class KrrCluster(BaseModel):
    cluster_id: int
    cluster_name: str
    latest_scan: Optional[datetime] = None

class KrrClustersResponse(BaseModel):
    status: str
    data: List[KrrCluster]

class KrrRecommendation(BaseModel):
    namespace: str
    workloadtype: str
    workloadname: str
    containername: str
    currentcpurequest: Optional[float]
    recommendedcpurequest: Optional[float]
    currentmemoryrequest: Optional[float]
    recommendedmemoryrequest: Optional[float]
    timestamp: Optional[datetime]

class KrrRecommendationsResponse(BaseModel):
    status: str
    cluster_name: str
    data: List[KrrRecommendation]
