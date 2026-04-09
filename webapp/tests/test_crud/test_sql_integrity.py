import pytest
from unittest.mock import MagicMock
from crud.entities import get_dynamic_items, get_scoped_top_tags, get_chain
from crud.costs import get_daily_costs

def test_sql_get_chain_structure():
    """Verify the recursive CTE structure for Top-Down navigation."""
    cursor = MagicMock()
    get_chain(cursor, 123)
    
    sql = cursor.execute.call_args[0][0]
    params = cursor.execute.call_args[0][1]
    
    assert "WITH RECURSIVE Path AS" in sql
    assert "UNION ALL" in sql
    assert "ORDER BY depth DESC" in sql
    assert params == (123,)

def test_sql_get_dynamic_items_complex_filter():
    """Verify the SubTree + Paths + ValidIds + UniqueNodes query."""
    cursor = MagicMock()
    tags = {"env": "prod", "team": "data"}
    get_dynamic_items(cursor, 1, tags)
    
    sql = cursor.execute.call_args[0][0]
    params = cursor.execute.call_args[0][1]
    
    assert "WITH RECURSIVE SubTree AS" in sql
    assert "Paths AS" in sql
    assert "ValidIds AS" in sql
    assert "UniqueNodes AS" in sql
    
    assert params[0] == 1 # scope_id
    assert "env" in params
    assert "prod" in params
    assert params[-1] == 1 # exclusion of scope_id at the end

@pytest.mark.skip(reason="Skipping due to exchange rate API")
def test_sql_get_daily_costs_timescaledb():
    """Verify TimescaleDB gap-filling SQL structure."""
    cursor = MagicMock()
    from datetime import date
    get_daily_costs(cursor, 1, None, start_date=date(2024,1,1), end_date=date(2024,1,31))
    
    sql = cursor.execute.call_args[0][0]
    
    assert "time_bucket_gapfill" in sql
    assert "COALESCE(SUM(c.BilledCost), 0.0)" in sql
    assert "GROUP BY bucket" in sql

def test_sql_get_scoped_top_tags_recursive():
    """Verify the recursive SubTree + Stats query for tag analysis."""
    cursor = MagicMock()
    get_scoped_top_tags(cursor, 1, limit=5)
    
    sql = cursor.execute.call_args[0][0]
    params = cursor.execute.call_args[0][1]
    
    assert "WITH RECURSIVE SubTree AS" in sql
    assert "Stats AS" in sql
    assert "SELECT COUNT(*) as total_count FROM SubTree" in sql
    assert "jsonb_object_keys(s.Tags) as key" in sql
    assert params == (1, 5)
