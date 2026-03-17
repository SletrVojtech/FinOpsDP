import urllib.parse
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from db.database import get_db_cursor
from crud import entities

router = APIRouter(tags=["Web UI"])
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Default page"""
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/ui/scope/{node_id}", response_class=HTMLResponse)
@router.get("/ui/scope/", response_class=HTMLResponse)
def get_scope(request: Request, node_id: int = None, cursor = Depends(get_db_cursor)):
    
    # Parse tags from the query
    active_tags = {}
    for param_name, param_value in request.query_params.items():
        if param_name.startswith("tag_") and param_value:
            clean_key = param_name[4:]
            active_tags[clean_key] = param_value

    # And reconstruct them into a future query
    current_qs = ""
    if active_tags:
        current_qs = "&" + urllib.parse.urlencode({f"tag_{k}": v for k, v in active_tags.items()})

    # Get the chain of entities and most represented tages for current scope
    chain = entities.get_chain(cursor, node_id)
    top_tags = entities.get_scoped_top_tags(cursor, node_id)
    
    # Create a stackable filter query
    items = entities.get_dynamic_items(cursor, node_id, active_tags)

    return templates.TemplateResponse("partial/scope_view.html", {
        "request": request,
        "current_scope_id": node_id or "",
        "chain": chain,
        "top_tags": top_tags,
        "items": items,
        "active_tags": active_tags,
        "current_qs": current_qs,
    })

@router.get("/ui/tag_values", response_class=HTMLResponse)
def get_tag_values(request: Request, scope_id: str = "", tag_key: str = None, current_qs: str = "", cursor = Depends(get_db_cursor)):
    """Generates buttons for tag values in current scope"""
    if not tag_key:
        return HTMLResponse("")
        
    scope_int = int(scope_id) if scope_id else None
    values = entities.get_scoped_tag_values(cursor, scope_int, tag_key)
    
    return templates.TemplateResponse("partial/tag_values.html", {
        "request": request,
        "scope_id": scope_id,
        "tag_key": tag_key,
        "values": values,
        "current_qs": current_qs
    })