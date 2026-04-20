import json
from typing import List, Dict

def get_exact_excluded_patterns(db_cursor, scope_id: int, tags: Dict[str, str]) -> List[str]:
    """Retrieve the exact excluded VM patterns configured for a given scope and tags."""
    query = """
        SELECT ExcludedPatterns FROM Rules
        WHERE ScopeId = %(scope_id)s 
          AND Tags @> %(tags)s::jsonb 
          AND Tags <@ %(tags)s::jsonb
          AND RuleType = 'downsizing_exclusion'
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
        SELECT ExcludedPatterns FROM Rules
        WHERE ScopeId = %(scope_id)s
          AND Tags <@ %(entity_tags)s::jsonb
          AND RuleType = 'downsizing_exclusion';
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
        INSERT INTO Rules (ScopeId, Tags, ExcludedPatterns, RuleType)
        VALUES (%(scope_id)s, %(tags)s::jsonb, %(patterns_json)s::jsonb, 'downsizing_exclusion')
        ON CONFLICT (ScopeId, Tags)
        DO UPDATE SET ExcludedPatterns = EXCLUDED.ExcludedPatterns, RuleType = 'downsizing_exclusion';
    """
    db_cursor.execute(query, {
        "scope_id": scope_id,
        "tags": tags_json,
        "patterns_json": patterns_json
    })

def get_tag_filtering_rules(db_cursor) -> List[Dict]:
    """Retrieve all tag filtering rules globally."""
    query = """
        SELECT Id, ExcludedPatterns FROM Rules
        WHERE RuleType = 'tag_filter'
        ORDER BY Id DESC;
    """
    db_cursor.execute(query)
    
    rules = []
    for row in db_cursor.fetchall():
        pattern = ""
        # Safely extract the first pattern from the JSONB array since we store one per rule for tag filters
        if row[1] and isinstance(row[1], list) and len(row[1]) > 0:
            pattern = row[1][0]
        rules.append({"id": row[0], "pattern": pattern})
    return rules

def add_tag_filtering_rule(db_cursor, pattern: str):
    """Add a new global tag filter rule."""
    query = """
        INSERT INTO Rules (ScopeId, Tags, ExcludedPatterns, RuleType)
        VALUES (0, '{}'::jsonb, %(patterns_json)s::jsonb, 'tag_filter');
    """
    db_cursor.execute(query, {
        "patterns_json": json.dumps([pattern])
    })

def delete_rule(db_cursor, rule_id: int):
    """Delete a rule by its ID."""
    db_cursor.execute("DELETE FROM Rules WHERE Id = %(rule_id)s", {"rule_id": rule_id})
