import urllib.parse
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from db.database import get_db_cursor
from crud import rules
from services.utils import extract_active_tags
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["Web UI / Downsizing"])

@router.post("/ui/downsizing-rules", response_class=HTMLResponse)
async def ui_set_downsizing_rules(
    request: Request,
    scope_id: int = 0,
    cursor=Depends(get_db_cursor)
):
    """UI endpoint to update downsizing rules and return the refreshed card."""
    form_data = await request.form()
    excluded_patterns_str = form_data.get("excluded_patterns", "")
    patterns = [p.strip() for p in excluded_patterns_str.split(",") if p.strip()]
    
    active_tags = extract_active_tags(request)
    rules.set_excluded_patterns(cursor, scope_id, active_tags, patterns)
    cursor.connection.commit()
    
    # Re-render the card partial
    current_qs = urllib.parse.urlencode({f"tag_{k}": v for k, v in active_tags.items()})
    
    return templates.TemplateResponse(request, "partial/downsizing_rules_card.html", {
        "scope_id": scope_id,
        "current_qs": current_qs,
        "patterns": patterns,
        "active_tags": active_tags
    })
