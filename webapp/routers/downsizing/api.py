"""
Downsizing REST API Router.

Exposes JSON endpoints for VM rightsizing recommendations and exclusion
rule management. All endpoints are prefixed ``/api/v1`` and tagged
*API / Downsizing*.
"""

from fastapi import APIRouter, Depends, Request, Query
from db.database import get_db_cursor
from crud import rules
from services import downsizing as downsizing_service
from services.utils import extract_active_tags
from .schemas import (
    DownsizingRulesRequest,
    DownsizingRulesResponse,
    SuccessResponse,
    DownsizingResponse
)

router = APIRouter(prefix="/api/v1", tags=["API / Downsizing"])

@router.post("/downsizing-rules", response_model=SuccessResponse)
def api_set_downsizing_rules(
    request: Request,
    payload: DownsizingRulesRequest,
    scope_id: int = 0,
    cursor=Depends(get_db_cursor)
):
    """Save or update the VM exclusion patterns for the current scope and tags.

    Args:
        request (Request): Incoming request (provides tag query params).
        payload (DownsizingRulesRequest): Request body with
            ``excluded_patterns`` list.
        scope_id (int): Entity scope ID. Defaults to 0.
        cursor: Injected DB cursor.

    Returns:
        SuccessResponse: ``{"status": "success"}``.
    """
    active_tags = extract_active_tags(request)
    rules.set_excluded_patterns(cursor, scope_id, active_tags, payload.excluded_patterns)
    cursor.connection.commit()
    return {"status": "success"}

@router.get("/downsizing-rules", response_model=DownsizingRulesResponse)
def api_get_downsizing_rules(
    request: Request,
    scope_id: int = 0,
    cursor=Depends(get_db_cursor)
):
    """Return VM exclusion patterns for the current scope and tags.

    Args:
        request (Request): Incoming request (provides tag query params).
        scope_id (int): Entity scope ID. Defaults to 0.
        cursor: Injected DB cursor.

    Returns:
        DownsizingRulesResponse: Payload with ``excluded_patterns`` list.
    """
    active_tags = extract_active_tags(request)
    patterns = rules.get_exact_excluded_patterns(cursor, scope_id, active_tags)
    return {"status": "success", "excluded_patterns": patterns}

@router.get("/downsizing/{entity_id}", response_model=DownsizingResponse)
def get_downsizing_recommendation(
    entity_id: int,
    scope_id: int = Query(0, description="Scope ID pro filtrování pravidel"),
    analysis_days: int = Query(30, description="Počet dní pro analýzu"),
    target_cpu: float = Query(85.0, description="Cílové zatížení CPU v %"),
    target_ram: float = Query(80.0, description="Cílové zatížení RAM v %"),
    cursor=Depends(get_db_cursor)
):
    """Return a rightsizing recommendation for the given VM instance.

    Resolves applicable exclusion patterns from the entity's tag set, then
    delegates to :func:`~services.downsizing.evaluate_downsizing`.

    Args:
        entity_id (int): Entity ID of the VM to evaluate.
        scope_id (int): Scope ID for exclusion-rule lookup. Defaults to 0.
        analysis_days (int): Telemetry lookback window in days. Defaults to 30.
        target_cpu (float): Target CPU utilisation (%). Defaults to 85.
        target_ram (float): Target RAM utilisation (%). Defaults to 80.
        cursor: Injected DB cursor.

    Returns:
        DownsizingResponse: Recommendation payload.
    """
    cursor.execute("SELECT Tags FROM Entities WHERE Id = %(entity_id)s", {"entity_id": entity_id})
    row = cursor.fetchone()
    entity_tags = row[0] if row and row[0] else {}

    auto_excluded = rules.get_entity_excluded_patterns(cursor, scope_id, entity_tags)

    result = downsizing_service.evaluate_downsizing(
        db_cursor=cursor,
        resource_id=entity_id,
        analysis_days=analysis_days,
        target_cpu_util=target_cpu,
        target_ram_util=target_ram,
        excluded_filters=auto_excluded
    )
    
    return result
