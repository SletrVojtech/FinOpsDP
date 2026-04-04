import pytest
from datetime import date
from crud.kube import get_daily_metric_allocation
from unittest.mock import MagicMock

def test_get_daily_metric_allocation(mock_cursor):
    mock_cursor.fetchall.return_value = [
        (date(2026, 3, 1), "ns1", 0.6)
    ]
    
    res = get_daily_metric_allocation(
        mock_cursor, 1, "cpu", 
        start_date=date(2026, 3, 1), end_date=date(2026, 3, 2)
    )
    
    assert len(res) == 1
    assert res[0][1] == "ns1"
    assert "WITH DailyNamespaceMetric_Raw" in mock_cursor.execute.call_args[0][0]
    # Check params
    assert mock_cursor.execute.call_args[0][1][2] == 1 # cluster_id
    assert mock_cursor.execute.call_args[0][1][3] == "cpu" # metric_name
