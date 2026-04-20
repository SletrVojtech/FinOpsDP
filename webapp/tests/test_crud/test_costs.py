import json
import pytest
from datetime import date
from unittest.mock import MagicMock
from crud.costs import _build_scope_cte, set_budget, save_forecast_snapshot, save_anomalies, get_daily_costs_by_tag_key, get_dashboard_anomalies, mark_anomaly_seen

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

def test_set_budget_insert_path():
    """Verify set_budget inserts when no existing row is found."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None # No existing budget
    
    target_month = date(2024, 1, 1)
    set_budget(cursor, 1, {"env": "prod"}, target_month, 1000.0)
    
    # Should call SELECT then INSERT
    assert cursor.execute.call_count == 2
    last_call = cursor.execute.call_args_list[1][0]
    assert "INSERT INTO Budgets" in last_call[0]
    assert 1000.0 in last_call[1]

def test_set_budget_update_path():
    """Verify set_budget updates when existing row is found."""
    cursor = MagicMock()
    cursor.fetchone.return_value = [10] # Existing ID 10
    
    target_month = date(2024, 1, 1)
    set_budget(cursor, 1, {"env": "prod"}, target_month, 2000.0)
    
    assert cursor.execute.call_count == 2
    last_call = cursor.execute.call_args_list[1][0]
    assert "UPDATE Budgets SET LimitAmount" in last_call[0]
    assert 2000.0 in last_call[1]

def test_save_forecast_snapshot():
    """Verify forecast snapshot insertion with ON CONFLICT DO UPDATE."""
    cursor = MagicMock()
    target_month = date(2024, 1, 1)
    
    save_forecast_snapshot(cursor, 1, {"env": "prod"}, target_month, 1500.5, {"2024-01-01": 50.0})
    
    assert cursor.execute.call_count == 1
    args = cursor.execute.call_args[0]
    assert "INSERT INTO ForecastHistory" in args[0]
    assert "ON CONFLICT" in args[0]
    assert args[1][0] == 1 # scope_id
    assert args[1][2] == target_month

def test_save_anomalies():
    """Verify anomaly insertion for each entry in a list, including type."""
    cursor = MagicMock()
    anomalies = [
        {"date": date(2024, 1, 1), "actual": 100, "predicted": 80, "threshold": 110, "delta": 20, "type": "cost"},
        {"date": date(2024, 1, 2), "actual": 120, "predicted": 85, "threshold": 115, "delta": 35, "type": "budget"}
    ]
    
    save_anomalies(cursor, 1, {"env": "prod"}, anomalies)
    
    assert cursor.execute.call_count == 2
    first_call_params = cursor.execute.call_args_list[0][0][1]
    assert first_call_params[2] == date(2024, 1, 1)
    assert first_call_params[3] == "cost" # anomaly type
    assert first_call_params[4] == 100 # actual cost

    second_call_params = cursor.execute.call_args_list[1][0][1]
    assert second_call_params[3] == "budget"

def test_get_dashboard_anomalies():
    """Verify fetching dashboard anomalies with filters."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        (1, 10, "Resource1", {"env": "prod"}, date(2024,1,1), "cost", 100.0, 80.0, 110.0, 20.0, False, None)
    ]
    
    res = get_dashboard_anomalies(cursor, date(2024,1,1), date(2024,1,31), only_unseen=True)
    
    assert len(res) == 1
    assert res[0]["id"] == 1
    assert res[0]["type"] == "cost"
    assert res[0]["is_seen"] is False
    
    # Verify SQL filter
    args = cursor.execute.call_args[0]
    assert "c.IsSeen = FALSE" in args[0]

def test_mark_anomaly_seen():
    """Verify marking anomaly as seen by ID."""
    cursor = MagicMock()
    mark_anomaly_seen(cursor, 123)
    
    args = cursor.execute.call_args[0]
    assert "UPDATE CostAnomalies SET IsSeen = TRUE" in args[0]
    assert args[1][0] == 123

def test_get_daily_costs_by_tag_key():
    """Verify SQL construction for tag-based cost grouping."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [[date(2024,1,1), "prod", 100.0]]
    
    res = get_daily_costs_by_tag_key(cursor, 1, None, "env", date(2024,1,1), date(2024,1,2))
    
    assert len(res) == 1
    assert res[0]["tag_value"] == "prod"
    
    # Verify tag_key was passed to SQL
    args = cursor.execute.call_args[0]
    assert "env" in args[1]
    assert "Tags->>%s" in args[0]


from crud.costs import get_forecast_quality

def test_get_forecast_quality():
    """Verify get_forecast_quality logic and calculations."""
    cursor = MagicMock()
    from datetime import datetime
    # Columns: ScopeId, ResourceName, Tags, ForecastDate, ProjectedAmount, DailyForecasts, CalculatedAt
    cursor.fetchall.return_value = [
        (1, "Scope A", {"env": "prod"}, date(2024, 1, 1), 80.0, {"2024-01-01": 40.0, "2024-01-02": 40.0}, datetime(2024, 1, 1, 10, 0)),
        (1, "Scope A", {"env": "prod"}, date(2024, 1, 2), 120.0, {"2024-01-01": 60.0, "2024-01-02": 60.0}, datetime(2024, 1, 2, 10, 0))
    ]
    
    target_month = date(2024, 1, 1)
    results = get_forecast_quality(cursor, target_month)
    
    assert len(results) == 1
    assert results[0]["scope_id"] == 1
    # Average of 80 and 120
    assert results[0]["projected_amount"] == 100.0
    # Latest is 120
    assert results[0]["actual_amount"] == 120.0
    assert results[0]["variance"] == 20.0
    assert results[0]["accuracy"] == 80.0
    
    # Ensure nested dict conversion worked
    assert results[0]["daily_actuals"]["2024-01-01"] == 60.0
    assert results[0]["daily_forecasts"]["2024-01-01"] == 50.0
