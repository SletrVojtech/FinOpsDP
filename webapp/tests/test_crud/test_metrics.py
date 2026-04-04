import pytest
from crud.metrics import get_available_metric_names, get_metric_data
from unittest.mock import MagicMock
from datetime import datetime

def test_get_available_metric_names(mock_cursor):
    mock_cursor.fetchall.return_value = [("cpu_util",), ("ram_util",)]
    
    names = get_available_metric_names(mock_cursor, 1)
    
    assert names == ["cpu_util", "ram_util"]
    assert "WHERE EntityId = %s" in mock_cursor.execute.call_args[0][0]

def test_get_metric_data_raw(mock_cursor):
    # Mocking _resolve_data_source result
    mock_cursor.fetchone.return_value = ("Metrics", False)
    
    # Mocking fetchall for metric entries
    mock_cursor.fetchall.return_value = [
        (datetime(2026, 3, 1, 10, 0, 0), 10.0, 20.0, 5.0, 100.0, 10)
    ]
    
    data = get_metric_data(mock_cursor, 1, "cpu_util")
    
    assert len(data) == 1
    assert data[0]["avg"] == 10.0
    assert data[0]["max"] == 20.0
    assert "time_bucket(%s::interval, Timestamp)" in mock_cursor.execute.call_args[0][0]

def test_get_metric_data_cagg(mock_cursor):
    # Mocking _resolve_data_source result
    mock_cursor.fetchone.return_value = ("Metrics_Hourly", True)
    
    mock_cursor.fetchall.return_value = [
        (datetime(2026, 3, 1, 10, 0, 0), 10.0, 20.0, 5.0, 100.0, 10)
    ]
    
    data = get_metric_data(mock_cursor, 1, "cpu_util")
    
    assert len(data) == 1
    assert "FROM Metrics_Hourly" in mock_cursor.execute.call_args[0][0]
    assert "avg_value" in mock_cursor.execute.call_args[0][0]
