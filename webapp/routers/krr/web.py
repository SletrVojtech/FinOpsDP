from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from db.database import get_db_cursor
from crud import krr
from services.utils import humanize_memory, humanize_cpu
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["Web UI / KRR"])

@router.get("/ui/krr", response_class=HTMLResponse)
def krr_index(request: Request, cursor=Depends(get_db_cursor)):
    """Lists all available clusters with reccomendations."""
    clusters = krr.get_krr_clusters(cursor)
    return templates.TemplateResponse(request, "krr_dashboard.html", {
        "clusters": clusters
    })

@router.get("/ui/krr/{cluster_id}", response_class=HTMLResponse)
def krr_detail(request: Request, cluster_id: int, cursor=Depends(get_db_cursor)):
    """Print out reccomendations for given cluster."""
    cluster_name = krr.get_cluster_name(cursor, cluster_id)
    raw_recommendations = krr.get_krr_recommendations_for_cluster(cursor, cluster_id)

    recommendations = []
    for row in raw_recommendations:
        clean_row = dict(row)
        
        clean_row['currentcpurequest'] = humanize_cpu(row['currentcpurequest'])
        clean_row['recommendedcpurequest'] = humanize_cpu(row['recommendedcpurequest'])
        
        clean_row['currentmemoryrequest'] = humanize_memory(row['currentmemoryrequest'])
        clean_row['recommendedmemoryrequest'] = humanize_memory(row['recommendedmemoryrequest'])
        
        recommendations.append(clean_row)

    return templates.TemplateResponse(request, "krr_report.html", {
        "cluster_name": cluster_name,
        "recommendations": recommendations
    })
