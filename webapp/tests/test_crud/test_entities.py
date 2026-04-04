import pytest
from crud.entities import get_roots, get_children, get_chain
from unittest.mock import MagicMock

def test_get_roots(mock_cursor):
    mock_cursor.fetchall.return_value = [
        (1, "Sub 1", "Azure", True),
        (2, "Sub 2", "AWS", False)
    ]
    
    roots = get_roots(mock_cursor)
    
    assert len(roots) == 2
    assert roots[0] == {"id": 1, "name": "Sub 1", "provider": "Azure", "has_children": True}
    assert roots[1] == {"id": 2, "name": "Sub 2", "provider": "AWS", "has_children": False}
    assert "WHERE ParentId = 0" in mock_cursor.execute.call_args[0][0]

def test_get_children(mock_cursor):
    mock_cursor.fetchall.return_value = [
        (10, "RG 1", "resource_group", True)
    ]
    
    children = get_children(mock_cursor, 1)
    
    assert len(children) == 1
    assert children[0]["name"] == "RG 1"
    assert children[0]["type"] == "resource_group"
    # Verify parent_id was passed to execute
    assert mock_cursor.execute.call_args[0][1] == (1,)

def test_get_chain(mock_cursor):
    # Mocking recursion result: Root -> Parent -> Child
    mock_cursor.fetchall.return_value = [
        (1, "Root"),
        (5, "Parent"),
        (10, "Child")
    ]
    
    chain = get_chain(mock_cursor, 10)
    
    assert len(chain) == 3
    assert chain[0]["id"] == 1
    assert chain[2]["id"] == 10
    assert "WITH RECURSIVE Path" in mock_cursor.execute.call_args[0][0]

def test_get_chain_root():
    assert get_chain(MagicMock(), 0) == []
