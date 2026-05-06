"""
Core REST API Router.

Exposes JSON endpoints for entity hierarchy navigation and global
tag-filter rule management. All endpoints are prefixed ``/api/v1``
and tagged *API / Core*.
"""

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
    """Return the root-level entities of the hierarchy.

    Args:
        cursor: Injected DB cursor.

    Returns:
        RootsResponse: Success payload with a list of root entities.
    """
    data = entities.get_roots(cursor)
    return {"status": "success", "data": data}

@router.get("/children/{parent_id}", response_model=ChildrenResponse)
def api_get_children(parent_id: int, cursor=Depends(get_db_cursor)):
    """Return direct children of a given entity node.

    Args:
        parent_id (int): Entity ID of the parent node.
        cursor: Injected DB cursor.

    Returns:
        ChildrenResponse: Success payload with a list of child entities.
    """
    data = entities.get_children(cursor, parent_id)
    return {"status": "success", "data": data}

@router.get("/scopes/{scope_id}/tags/{tag_key}/values", response_model=TagValuesResponse)
def api_get_tag_values(scope_id: int, tag_key: str, cursor=Depends(get_db_cursor)):
    """Return distinct values and frequencies for a tag key within a scope.

    Args:
        scope_id (int): Root entity ID for the scope subtree.
        tag_key (str): Tag key to aggregate values for.
        cursor: Injected DB cursor.

    Returns:
        TagValuesResponse: Success payload with list of ``{value, count}`` dicts.
    """
    data = entities.get_scoped_tag_values(cursor, scope_id, tag_key)
    return {"status": "success", "data": data}

@router.get("/rules", response_model=TagRulesResponse)
def api_get_rules(cursor=Depends(get_db_cursor)):
    """Return all global tag-filter rules.

    Args:
        cursor: Injected DB cursor.

    Returns:
        TagRulesResponse: Success payload with list of rule dicts.
    """
    data = rules.get_tag_filtering_rules(cursor)
    return {"status": "success", "data": data}

@router.post("/rules", response_model=SuccessResponse)
def api_add_rule(payload: CreateTagRuleRequest, cursor=Depends(get_db_cursor)):
    """Create a new global tag-filter rule.

    Args:
        payload (CreateTagRuleRequest): Request body with ``pattern``.
        cursor: Injected DB cursor.

    Returns:
        SuccessResponse: ``{"status": "success"}``.

    Raises:
        HTTPException: 400 if the pattern is empty or blank.
    """
    if payload.pattern and payload.pattern.strip():
        rules.add_tag_filtering_rule(cursor, payload.pattern.strip())
        cursor.connection.commit()
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Invalid pattern")

@router.delete("/rules/{rule_id}", response_model=SuccessResponse)
def api_delete_rule(rule_id: int, cursor=Depends(get_db_cursor)):
    """Delete a global tag-filter rule by ID.

    Args:
        rule_id (int): Primary key of the rule to delete.
        cursor: Injected DB cursor.

    Returns:
        SuccessResponse: ``{"status": "success"}``.
    """
    rules.delete_rule(cursor, rule_id)
    cursor.connection.commit()
    return {"status": "success"}
