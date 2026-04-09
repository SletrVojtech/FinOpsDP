import json
import pytest
from unittest.mock import MagicMock
from crud.downsizing_rules import (
    set_excluded_patterns,
    get_exact_excluded_patterns,
    get_entity_excluded_patterns
)

def test_set_excluded_patterns():
    """Verify rules insertion/upsert with correct JSON serialization."""
    cursor = MagicMock()
    scope_id = 123
    tags = {"env": "prod"}
    patterns = ["burstable", "t3.%"]
    
    set_excluded_patterns(cursor, scope_id, tags, patterns)
    
    assert cursor.execute.call_count == 1
    args = cursor.execute.call_args[0]
    params = args[1]
    
    assert "INSERT INTO DownsizingRules" in args[0]
    assert params["scope_id"] == scope_id
    # Check that tags and patterns are serialized to JSON strings
    assert params["tags"] == json.dumps(tags)
    assert params["patterns_json"] == json.dumps(patterns)

def test_get_exact_excluded_patterns_found():
    """Verify fetching rule for exact scope and tags."""
    cursor = MagicMock()
    cursor.fetchone.return_value = (["m5.large"],)
    
    tags = {"env": "prod", "tier": "db"}
    res = get_exact_excluded_patterns(cursor, 1, tags)
    
    assert res == ["m5.large"]
    args = cursor.execute.call_args[0]
    # Verify exact match SQL logic (Tags @> AND Tags <@)
    assert "Tags @>" in args[0]
    assert "Tags <@" in args[0]
    assert args[1]["tags"] == json.dumps(tags)

def test_get_exact_excluded_patterns_not_found():
    """Verify empty list returned when no rule exists."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    
    res = get_exact_excluded_patterns(cursor, 1, {})
    assert res == []

def test_get_entity_excluded_patterns_resolution():
    """
    Verify resolution logic where an entity might match multiple rules 
    (e.g., a specific tag-based rule and a generic scope-wide rule).
    """
    cursor = MagicMock()
    # Mock multiple matching rules:
    # Scope-wide rule: []
    # Prod-specific rule: ["burstable"]
    # DB-specific rule: ["m5.large"]
    cursor.fetchall.return_value = [
        (["burstable"],),
        (["m5.large"],),
        ([],)
    ]
    
    entity_tags = {"env": "prod", "tier": "db", "app": "billing"}
    res = get_entity_excluded_patterns(cursor, 1, entity_tags)
    
    # Verify union and uniqueness
    assert "burstable" in res
    assert "m5.large" in res
    assert len(res) == 2
    
    args = cursor.execute.call_args[0]
    # Verify resolution logic uses subset operator
    assert "Tags <@" in args[0]
    assert args[1]["entity_tags"] == json.dumps(entity_tags)

def test_get_entity_excluded_patterns_empty():
    """Verify behavior when no rules apply."""
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    
    res = get_entity_excluded_patterns(cursor, 1, {"env": "dev"})
    assert res == []
