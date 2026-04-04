import pytest
from datetime import date
from services.kube_chargeback import get_daily_namespace_allocation
from unittest.mock import MagicMock

def test_get_daily_namespace_allocation(mocker):
    """Test K8s namespace allocation logic with mocked repository."""
    mock_cursor = MagicMock()
    
    # Mocking repository calls
    mock_cpu = mocker.patch("crud.kube.get_daily_cpu_allocation")
    mock_ram = mocker.patch("crud.kube.get_daily_memory_allocation")
    
    # Date range
    start = date(2026, 3, 1)
    end = date(2026, 3, 3)
    cluster_id = 1
    
    # Mock CPU
    mock_cpu.return_value = [
        (date(2026, 3, 1), "ns1", 0.6),
        (date(2026, 3, 1), "ns2", 0.4),
        (date(2026, 3, 2), "ns1", 0.7),
        (date(2026, 3, 2), "ns2", 0.3)
    ]
    
    # Mock RAM
    mock_ram.return_value = [
        (date(2026, 3, 1), "ns1", 0.4),
        (date(2026, 3, 1), "ns2", 0.6),
        (date(2026, 3, 2), "ns1", 0.3),
        (date(2026, 3, 2), "ns2", 0.7)
    ]
    
    # Cluster costs: 100.0 each day
    daily_cluster_costs = {
        "2026-03-01": 100.0,
        "2026-03-02": 200.0
    }
    
    # Weights: CPU=0.70, RAM=0.30
    
    # Act
    result = get_daily_namespace_allocation(
        mock_cursor, cluster_id, base_date=None, 
        daily_cluster_costs=daily_cluster_costs,
        start_date=start, end_date=end,
        return_ui_format=False
    )
    
    # Assert
    assert "ns1" in result
    assert "ns2" in result
    assert result["ns1"]["2026-03-01"] == 54.0
    assert result["ns2"]["2026-03-01"] == 46.0
    assert result["ns1"]["2026-03-02"] == 116.0
    assert result["ns2"]["2026-03-02"] == 84.0

def test_get_daily_namespace_allocation_ui_format(mocker):
    """Test that result reflects chart.js compatible structure."""
    mock_cursor = MagicMock()
    mocker.patch("crud.kube.get_daily_cpu_allocation", return_value=[])
    mocker.patch("crud.kube.get_daily_memory_allocation", return_value=[])
    
    res = get_daily_namespace_allocation(
        mock_cursor, 1, base_date=None, 
        daily_cluster_costs={},
        start_date=date(2026, 3, 1), end_date=date(2026, 3, 2),
        return_ui_format=True
    )
    
    assert "labels" in res
    assert "datasets" in res
    assert res["labels"] == ["2026-03-01"]
