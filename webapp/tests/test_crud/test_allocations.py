import pytest
from crud.allocations import get_allocation_rules, add_allocation_rule, delete_allocation_rule

import json

def test_get_allocation_rules(mock_cursor):
    mock_cursor.fetchall.return_value = [
        (1, "Rule 1", {"env": "prod"}, {"dept": "it"}, 50.0)
    ]
    
    rules = get_allocation_rules(mock_cursor)
    
    assert len(rules) == 1
    assert rules[0]["rule_name"] == "Rule 1"
    assert rules[0]["source_tags"] == {"env": "prod"}
    assert rules[0]["percentage"] == 50.0

def test_add_allocation_rule(mock_cursor):
    add_allocation_rule(mock_cursor, "Rule 2", {"a": "b"}, {"c": "d"}, 100.0)
    
    assert mock_cursor.execute.called
    args = mock_cursor.execute.call_args[0]
    assert "INSERT INTO AllocationRules" in args[0]
    assert args[1][0] == "Rule 2"
    assert json.loads(args[1][1]) == {"a": "b"}
    assert args[1][3] == 100.0

def test_delete_allocation_rule(mock_cursor):
    delete_allocation_rule(mock_cursor, 123)
    assert mock_cursor.execute.called
    assert mock_cursor.execute.call_args[0][1] == (123,)
