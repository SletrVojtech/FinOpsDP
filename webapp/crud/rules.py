"""
Downsizing and Tag Filtering Rules Module.

Provides database operations for two rule types stored in the ``Rules``
table:

- ``downsizing_exclusion`` — scope-and-tag-scoped lists of VM instance
  type glob patterns to exclude from rightsizing recommendations.
- ``tag_filter`` — global patterns used to suppress noisy tag keys from
  the scope-explorer UI.
"""

import json
from typing import List, Dict

def get_exact_excluded_patterns(db_cursor, scope_id: int, tags: Dict[str, str]) -> List[str]:
    """Return the excluded VM patterns configured for an exact scope and tag combination.

    Performs an exact JSONB equality match on both sides (``@>`` and ``<@``)
    so only rules whose tag set is identical to ``tags`` are returned.

    Args:
        db_cursor: Active database cursor.
        scope_id (int): The scope entity ID to filter by.
        tags (dict): Exact tag key-value pairs to match.

    Returns:
        list[str]: List of glob patterns (e.g. ``["Standard_D*"]``),
            or an empty list if no rule exists.
    """
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
    """Return all excluded VM patterns applicable to an entity's tags in the given scope.

    Args:
        db_cursor: Active database cursor.
        scope_id (int): The scope entity ID to filter by.
        entity_tags (dict): The full tag set of the entity being evaluated.

    Returns:
        list[str]: Deduplicated list of glob patterns from all matching rules.
    """
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
    """Upsert the excluded VM patterns for a given scope and exact tag combination.

    Inserts a new rule or updates the existing one for the
    (``scope_id``, ``tags``) pair using ``ON CONFLICT … DO UPDATE``.

    Args:
        db_cursor: Active database cursor.
        scope_id (int): The scope entity ID.
        tags (dict): Exact tag key-value pairs identifying the rule.
        excluded_patterns (list[str]): New list of glob patterns to store.
    """
    # Ensure excluded_patterns is a valid JSON array for the JSONB column
    patterns_json = json.dumps(excluded_patterns)
    tags_json = json.dumps(tags)
    
    query = """
        INSERT INTO Rules (ScopeId, Tags, ExcludedPatterns, RuleType)
        VALUES (%(scope_id)s, %(tags)s::jsonb, %(patterns_json)s::jsonb, 'downsizing_exclusion')
        ON CONFLICT (ScopeId, Tags, RuleType)
        DO UPDATE SET ExcludedPatterns = EXCLUDED.ExcludedPatterns, RuleType = 'downsizing_exclusion';
    """
    db_cursor.execute(query, {
        "scope_id": scope_id,
        "tags": tags_json,
        "patterns_json": patterns_json
    })

def get_tag_filtering_rules(db_cursor) -> List[Dict]:
    """Return all global tag-filter rules.

    Args:
        db_cursor: Active database cursor.

    Returns:
        list: Dicts with keys ``id`` and ``pattern``, ordered by
            most-recently-created first.
    """
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
    """Insert a new global tag-filter rule.

    Args:
        db_cursor: Active database cursor.
        pattern (str): Glob pattern of the tag key to suppress
            (e.g. ``"aws:*"`` or ``"eks:*"``). The pattern is stored
            as a one-element JSONB array.
    """
    query = """
        INSERT INTO Rules (ScopeId, Tags, ExcludedPatterns, RuleType)
        VALUES (0, '{}'::jsonb, %(patterns_json)s::jsonb, 'tag_filter');
    """
    db_cursor.execute(query, {
        "patterns_json": json.dumps([pattern])
    })

def delete_rule(db_cursor, rule_id: int):
    """Delete a rule record by its primary key.

    Args:
        db_cursor: Active database cursor.
        rule_id (int): Primary key of the rule to delete.
    """
    db_cursor.execute("DELETE FROM Rules WHERE Id = %(rule_id)s", {"rule_id": rule_id})
