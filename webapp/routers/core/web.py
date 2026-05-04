import urllib.parse
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from db.database import get_db_cursor
from crud import entities, rules
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["Web UI / Core"])

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Default page"""
    return templates.TemplateResponse(request, "dashboard.html", {})

@router.get("/ui/scope/{node_id}", response_class=HTMLResponse)
@router.get("/ui/scope/", response_class=HTMLResponse)
def get_scope(request: Request, node_id: int = 0, cursor=Depends(get_db_cursor)):
    # Parse tags from the query
    active_tags = {}
    for param_name, param_value in request.query_params.items():
        if param_name.startswith("tag_") and param_value:
            clean_key = param_name[4:]
            active_tags[clean_key] = param_value

    # Reconstruct them into a future query
    current_qs = ""
    if active_tags:
        current_qs = "&" + urllib.parse.urlencode({f"tag_{k}": v for k, v in active_tags.items()})

    # Get the chain of entities and most represented tags for current scope
    chain = entities.get_chain(cursor, node_id)
    top_tags = entities.get_scoped_top_tags(cursor, node_id)
    
    # Create a stackable filter query
    items = entities.get_dynamic_items(cursor, node_id, active_tags)

    return templates.TemplateResponse(request, "partial/scope_view.html", {
        "current_scope_id": node_id,
        "chain": chain,
        "top_tags": top_tags,
        "items": items,
        "active_tags": active_tags,
        "current_qs": current_qs,
        "patterns": rules.get_exact_excluded_patterns(cursor, node_id, active_tags),
        "scope_id": node_id,
    })

@router.get("/ui/tag_values", response_class=HTMLResponse)
def get_tag_values(request: Request, scope_id: str = "", tag_key: str = None, current_qs: str = "", cursor=Depends(get_db_cursor)):
    """Generates buttons for tag values in current scope"""
    if not tag_key:
        return HTMLResponse("")
        
    try:
        scope_int = int(scope_id) if scope_id else 0
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid scope_id")
    values = entities.get_scoped_tag_values(cursor, scope_int, tag_key)
    
    return templates.TemplateResponse(request, "partial/tag_values.html", {
        "scope_id": scope_id,
        "tag_key": tag_key,
        "values": values,
        "current_qs": current_qs
    })

@router.get("/ui/rules", response_class=HTMLResponse)
def view_rules_dashboard(request: Request, cursor=Depends(get_db_cursor)):
    """Shows the generic tag-filtering rules dashboard"""
    tag_rules = rules.get_tag_filtering_rules(cursor)
    return templates.TemplateResponse(request, "rules_dashboard.html", {"rules": tag_rules})

@router.post("/ui/rules", response_class=HTMLResponse)
def add_tag_rule(request: Request, pattern: str = Form(...), cursor=Depends(get_db_cursor)):
    """Add a new tag filtering rule and update the view"""
    if pattern and pattern.strip():
        rules.add_tag_filtering_rule(cursor, pattern.strip())
        cursor.connection.commit()
    # Read back all and re-render
    tag_rules = rules.get_tag_filtering_rules(cursor)
    return templates.TemplateResponse(request, "rules_dashboard.html", {"rules": tag_rules})

@router.delete("/ui/rules/{rule_id}")
def delete_tag_rule(request: Request, rule_id: int, cursor=Depends(get_db_cursor)):
    """Delete a rule and return empty so htmx removes the row."""
    rules.delete_rule(cursor, rule_id)
    cursor.connection.commit()
    # Triggers an element removal on the UI
    return HTMLResponse("")
