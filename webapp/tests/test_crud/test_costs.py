import pytest
from crud.costs import _build_scope_cte

def test_build_scope_cte_no_tags():
    """Test CTE generation with only scope_id."""
    sql, params = _build_scope_cte(123, None)
    
    # Check that scope_id is included twice (for start and FilteredEntities exclude)
    assert params == [123, 123]
    assert "WHERE Id = %s" in sql
    assert "WHERE Id != %s" in sql
    assert "AND Tags->>" not in sql

def test_build_scope_cte_with_tags():
    """Test CTE generation with scope_id and multiple tags."""
    tags = {"env": "prod", "team": "data"}
    sql, params = _build_scope_cte(123, tags)
    
    # params: [scope_id, scope_id, key1, val1, key2, val2]
    assert len(params) == 6
    assert params[0] == 123
    assert params[1] == 123
    
    # Check for tag filtering SQL
    assert "AND Tags->>%s = %s" in sql

    assert "env" in params
    assert "prod" in params
    assert "team" in params
    assert "data" in params
