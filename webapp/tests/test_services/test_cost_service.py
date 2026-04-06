import pandas as pd
import pytest
from datetime import date, datetime, timedelta
from services.cost_service import (
    tags_match, _make_anomaly_entry, _prepare_dates_and_cutoff, 
    get_aggregated_daily_costs
)
from unittest.mock import MagicMock


def test_tags_match():
    """Test tags_match logic for rule attribution."""
    current = {"env": "prod", "service": "api"}
    rule_1 = {"env": "prod"}
    rule_2 = {"env": "stage"}
    rule_3 = {"env": "prod", "service": "api", "extra": "val"}
    rule_4 = {}

    assert tags_match(current, rule_1) is True
    assert tags_match(current, rule_2) is False
    assert tags_match(current, rule_3) is False
    assert tags_match(current, rule_4) is False

def test_make_anomaly_entry_dict():
    """Test _make_anomaly_entry with threshold dictionary (from DB)."""
    date_str = "2026-03-01"
    thresh_data = {
        "actual": 100.0,
        "threshold": 80.0,
        "delta": 20.0
    }
    entry = _make_anomaly_entry(date_str, 100.0, thresh_data)
    
    assert entry["date"] == date_str
    assert entry["is_anomaly"] is True
    assert entry["actual"] == 100.0
    assert entry["threshold"] == 80.0
    assert entry["delta"] == 20.0

def test_make_anomaly_entry_scalar():
    """Test _make_anomaly_entry with scalar threshold (from AutoETS)."""
    date_str = "2026-03-01"
    daily_cost = 50.0
    thresh_data = 40.0
    entry = _make_anomaly_entry(date_str, daily_cost, thresh_data)
    
    assert entry["date"] == date_str
    assert entry["is_anomaly"] is True
    assert entry["actual"] == 50.0
    assert entry["threshold"] == 40.0
    assert entry["delta"] == 10.0

def test_make_anomaly_entry_none():
    """Test _make_anomaly_entry with no threshold data."""
    date_str = "2026-03-01"
    entry = _make_anomaly_entry(date_str, 25.0, None)
    
    assert entry["is_anomaly"] is False
    assert entry["actual"] == 25.0
    assert entry["threshold"] is None

def test_prepare_dates_and_cutoff(mocker):
    """Test date calculation logic for current month."""
    mock_cursor = MagicMock()
    # Mocking costs_crud.get_max_date
    mock_get_max_date = mocker.patch("crud.costs.get_max_date")
    
    # With actual data
    mock_get_max_date.return_value = [datetime(2026, 3, 15)]
    base, start, end, num_days, cutoff_obj, cutoff_day = _prepare_dates_and_cutoff(mock_cursor, "2026-03")
    
    assert base == date(2026, 3, 1)
    assert start == date(2026, 3, 1)
    assert end == date(2026, 4, 1)
    assert num_days == 31
    # 2026-03-15 is the data max, but SAFE_DAYS_TO_SUBTRACT is 3. 
    assert isinstance(cutoff_obj, date)
    assert 0 <= cutoff_day <= 31

def test_get_aggregated_daily_costs_with_allocation(mocker):
    """Verify that allocation rules are applied to base costs."""
    cursor = MagicMock()
    
    # Base costs: $100 on 2024-01-01
    mocker.patch("crud.costs.get_daily_costs", return_value=[{"date": "2024-01-01", "cost": 100.0}])
    mocker.patch("crud.costs.get_namespaces_for_tags", return_value=[])
    
    # Setup one allocation rule: 50% from 'other' to our scope
    mocker.patch("crud.allocations.get_allocation_rules", return_value=[
        {"id": 1, "source_tags": {"env": "other"}, "target_tags": {"env": "prod"}, "percentage": 50.0}
    ])
    
    # Source costs (for env=other): $200 on 2024-01-01
    # Mock get_daily_costs differently based on tags.
    def side_effect_costs(cur, sid, tags, **kwargs):
        if tags == {"env": "prod"}: return [{"date": "2024-01-01", "cost": 100.0}]
        if tags == {"env": "other"}: return [{"date": "2024-01-01", "cost": 200.0}]
        return []
        
    mocker.patch("crud.costs.get_daily_costs", side_effect=side_effect_costs)
    
    # Act
    costs = get_aggregated_daily_costs(cursor, scope_id=1, active_tags={"env": "prod"}, 
                                       start_date=date(2024,1,1), end_date=date(2024,1,2))
    
    # Assert: 100 base + 50% of 200 = 200 total
    assert costs["2024-01-01"] == 200.0

def test_calculate_chargeback_forecast_ml_path(mocker):
    """Verify the ML forecast path using mocked StatsForecast."""
    cursor = MagicMock()
    mocker.patch("services.cost_service._prepare_dates_and_cutoff", 
                 return_value=(date(2024,1,1), date(2024,1,1), date(2024,2,1), 31, date(2024,1,15), 15))
    mocker.patch("services.cost_service.get_aggregated_daily_costs", return_value={"2024-01-01": 50.0})
    mocker.patch("crud.costs.get_budget", return_value=1000.0)
    
    # Mock StatsForecast
    mock_sf_cls = mocker.patch("services.cost_service.StatsForecast")
    mock_sf = mock_sf_cls.return_value
    
    # Mock forecast result
    # Columns need to match what the service expects: ['ds', 'AutoETS']
    forecast_df = pd.DataFrame({
        'ds': [datetime(2024, 1, 16)],
        'AutoETS': [55.0]
    })
    mock_sf.forecast.return_value = forecast_df
    mock_sf.forecast_fitted_values.return_value = pd.DataFrame()
    
    from services.cost_service import calculate_chargeback_forecast
    res = calculate_chargeback_forecast(cursor, 1, {"env": "prod"}, "2024-01")
    
    assert res["budget"] == 1000.0
    # On 2024-01-16 (day 16), it should use the forecast cumulative which starts at cutoff
    assert res["forecast_cumulative"][15] is not None

def test_calculate_chargeback_forecast_sma_fallback(mocker):
    """Verify fallback to 15-day Simple Moving Average when ML model fails."""
    cursor = MagicMock()
    mocker.patch("services.cost_service._prepare_dates_and_cutoff", 
                 return_value=(date(2024,1,1), date(2024,1,1), date(2024,2,1), 31, date(2024,1,15), 15))
    
    # Recent history: 15 days of $100
    history = { (date(2024,1,15) - timedelta(days=i)).isoformat(): 100.0 for i in range(15) }
    mocker.patch("services.cost_service.get_aggregated_daily_costs", return_value=history)
    
    # Force StatsForecast to fail
    mocker.patch("services.cost_service.StatsForecast", side_effect=Exception("ML Error"))
    
    from services.cost_service import calculate_chargeback_forecast
    res = calculate_chargeback_forecast(cursor, 1, {"env": "prod"}, "2024-01")
    
    # Assert
    # SMA should be 100.0. Cumulative on day 16 should be (15 * 100) + 100 = 1600.
    assert res["forecast_cumulative"][15] == 1600.0 # Day 16 cumulative
    assert res["actual_daily"][14] == 100.0        # Day 15 actual
