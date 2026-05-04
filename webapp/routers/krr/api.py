from fastapi import APIRouter, Depends
from db.database import get_db_cursor
from crud import krr
from .schemas import (
    KrrClustersResponse,
    KrrRecommendationsResponse
)

router = APIRouter(prefix="/api/v1/krr", tags=["API / KRR"])

@router.get("/clusters", response_model=KrrClustersResponse)
def api_get_krr_clusters(cursor=Depends(get_db_cursor)):
    """Lists all available clusters with KRR recommendations."""
    clusters = krr.get_krr_clusters(cursor)
    return {"status": "success", "data": clusters}

@router.get("/clusters/{cluster_id}/recommendations", response_model=KrrRecommendationsResponse)
def api_get_krr_recommendations(cluster_id: int, cursor=Depends(get_db_cursor)):
    """Return recommendations for a given cluster."""
    cluster_name = krr.get_cluster_name(cursor, cluster_id)
    recommendations = krr.get_krr_recommendations_for_cluster(cursor, cluster_id)
    return {
        "status": "success",
        "cluster_name": cluster_name,
        "data": recommendations
    }
