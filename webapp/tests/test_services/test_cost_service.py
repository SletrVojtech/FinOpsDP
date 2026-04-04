import pytest
from datetime import date, datetime
from services.cost_service import tags_match, _make_anomaly_entry, _prepare_dates_and_cutoff
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
    
    # CASE 1: With actual data
    mock_get_max_date.return_value = [datetime(2026, 3, 15)]
    base, start, end, num_days, cutoff_obj, cutoff_day = _prepare_dates_and_cutoff(mock_cursor, "2026-03")
    
    assert base == date(2026, 3, 1)
    assert start == date(2026, 3, 1)
    assert end == date(2026, 4, 1)
    assert num_days == 31
    # 2026-03-15 is the data max, but SAFE_DAYS_TO_SUBTRACT is 3. 
    # Logic: if cutoff_obj > safe_max_date, then use safe_max_date.
    assert isinstance(cutoff_obj, date)
    assert 0 <= cutoff_day <= 31
