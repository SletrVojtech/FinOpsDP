from fastapi import APIRouter, Depends, HTTPException
from db.database import get_db_cursor
from crud import entities, rules
from .schemas import (
    RootsResponse,
    ChildrenResponse,
    TagValuesResponse,
    TagRulesResponse,
    CreateTagRuleRequest,
    SuccessResponse
)

router = APIRouter(prefix="/api/v1", tags=["API / Core"])

@router.get("/roots", response_model=RootsResponse)
def api_get_roots(cursor=Depends(get_db_cursor)):
    """Returns roots of the hierarchy."""
    data = entities.get_roots(cursor)
    return {"status": "success", "data": data}

@router.get("/children/{parent_id}", response_model=ChildrenResponse)
def api_get_children(parent_id: int, cursor=Depends(get_db_cursor)):
    """Returns children of given Id."""
    data = entities.get_children(cursor, parent_id)
    return {"status": "success", "data": data}

@router.get("/scopes/{scope_id}/tags/{tag_key}/values", response_model=TagValuesResponse)
def api_get_tag_values(scope_id: int, tag_key: str, cursor=Depends(get_db_cursor)):
    """Returns tag values for a given scope and tag key."""
    data = entities.get_scoped_tag_values(cursor, scope_id, tag_key)
    return {"status": "success", "data": data}

@router.get("/rules", response_model=TagRulesResponse)
def api_get_rules(cursor=Depends(get_db_cursor)):
    """Retrieve all global tag filtering rules."""
    data = rules.get_tag_filtering_rules(cursor)
    return {"status": "success", "data": data}

@router.post("/rules", response_model=SuccessResponse)
def api_add_rule(payload: CreateTagRuleRequest, cursor=Depends(get_db_cursor)):
    """Add a new global tag filter rule."""
    if payload.pattern and payload.pattern.strip():
        rules.add_tag_filtering_rule(cursor, payload.pattern.strip())
        cursor.connection.commit()
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Invalid pattern")

@router.delete("/rules/{rule_id}", response_model=SuccessResponse)
def api_delete_rule(rule_id: int, cursor=Depends(get_db_cursor)):
    """Delete a global tag filter rule."""
    rules.delete_rule(cursor, rule_id)
    cursor.connection.commit()
    return {"status": "success"}
