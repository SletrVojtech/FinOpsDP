import json
from typing import List, Dict

def get_exact_excluded_patterns(db_cursor, scope_id: int, tags: Dict[str, str]) -> List[str]:
    """Retrieve the exact excluded VM patterns configured for a given scope and tags."""
    query = """
        SELECT ExcludedPatterns FROM DownsizingRules
        WHERE ScopeId = %(scope_id)s AND Tags @> %(tags)s::jsonb AND Tags <@ %(tags)s::jsonb
        LIMIT 1;
    """
    db_cursor.execute(query, {
        "scope_id": scope_id,
        "tags": json.dumps(tags or {})
    })
    row = db_cursor.fetchone()
    return row[0] if row and row[0] else []


def get_entity_excluded_patterns(db_cursor, scope_id: int, entity_tags: Dict[str, str]) -> List[str]:
    """Retrieve the union of all excluded VM patterns applicable to the entity's tags in the given scope."""
    query = """
        SELECT ExcludedPatterns FROM DownsizingRules
        WHERE ScopeId = %(scope_id)s
          AND Tags <@ %(entity_tags)s::jsonb;
    """
    db_cursor.execute(query, {
        "scope_id": scope_id,
        "entity_tags": json.dumps(entity_tags or {})
    })
    
    rows = db_cursor.fetchall()
    all_patterns = []
    for row in rows:
        if row[0]: # ExcludedPatterns is a JSONB array or list
            all_patterns.extend(row[0])
    
    return list(set(all_patterns)) # Return unique patterns


def set_excluded_patterns(db_cursor, scope_id: int, tags: Dict[str, str], excluded_patterns: List[str]):
    """Set the excluded VM patterns for a given scope and tags."""
    # Ensure excluded_patterns is a valid JSON array for the JSONB column
    patterns_json = json.dumps(excluded_patterns)
    tags_json = json.dumps(tags)
    
    query = """
        INSERT INTO DownsizingRules (ScopeId, Tags, ExcludedPatterns)
        VALUES (%(scope_id)s, %(tags)s::jsonb, %(patterns_json)s::jsonb)
        ON CONFLICT (ScopeId, Tags)
        DO UPDATE SET ExcludedPatterns = EXCLUDED.ExcludedPatterns;
    """
    db_cursor.execute(query, {
        "scope_id": scope_id,
        "tags": tags_json,
        "patterns_json": patterns_json
    })
