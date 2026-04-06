import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from services.kube_chargeback import get_daily_namespace_allocation

@pytest.fixture
def mock_kube_crud(mocker):
    return {
        "cpu": mocker.patch("crud.kube.get_daily_cpu_allocation"),
        "mem": mocker.patch("crud.kube.get_daily_memory_allocation"),
    }

def test_weighted_allocation_math(mock_kube_crud):
    """Verify the 70% CPU / 30% RAM weighted allocation math."""
    cursor = MagicMock()
    # Mock CPU: Namespace 'A' has 10% (0.1), 'B' has 50% (0.5)
    mock_kube_crud["cpu"].return_value = [
        (date(2024, 1, 1), "ns-a", 0.1),
        (date(2024, 1, 1), "ns-b", 0.5),
    ]
    # Mock RAM: Namespace 'A' has 20% (0.2), 'B' has 30% (0.3)
    mock_kube_crud["mem"].return_value = [
        (date(2024, 1, 1), "ns-a", 0.2),
        (date(2024, 1, 1), "ns-b", 0.3),
    ]
    
    # Cluster cost for day: $100
    daily_costs = {"2024-01-01": 100.0}
    
    # Act
    res = get_daily_namespace_allocation(
        cursor, 1, base_date=None, 
        daily_cluster_costs=daily_costs,
        start_date=date(2024, 1, 1), end_date=date(2024, 1, 2),
        return_ui_format=False
    )
    
    # Assert
    # NS-A: 100 * (0.7*0.1 + 0.3*0.2) = 100 * (0.07 + 0.06) = 13.0
    # NS-B: 100 * (0.7*0.5 + 0.3*0.3) = 100 * (0.35 + 0.09) = 44.0
    assert res["ns-a"]["2024-01-01"] == 13.0
    assert res["ns-b"]["2024-01-01"] == 44.0

def test_allocation_gap_filling(mock_kube_crud):
    """Verify that namespaces are gap-filled across the entire date range."""
    cursor = MagicMock()
    # Day 1: Only ns-a
    # Day 2: Only ns-b
    mock_kube_crud["cpu"].return_value = [
        (date(2024, 1, 1), "ns-a", 1.0),
        (date(2024, 1, 2), "ns-b", 1.0),
    ]
    mock_kube_crud["mem"].return_value = []
    
    daily_costs = {"2024-01-01": 10.0, "2024-01-02": 20.0}
    
    # Act
    res = get_daily_namespace_allocation(
        cursor, 1, base_date=None,
        daily_cluster_costs=daily_costs,
        start_date=date(2024,1,1), end_date=date(2024,1,3), # 2 days
        return_ui_format=False
    )
    
    # Assert
    # ns-a should exist for day 2 even if costs are 0
    assert "2024-01-01" in res["ns-a"]
    assert "2024-01-02" in res["ns-a"]
    assert res["ns-a"]["2024-01-02"] == 0.0
    
    assert "2024-01-01" in res["ns-b"]
    assert res["ns-b"]["2024-01-01"] == 0.0

def test_allocation_ui_format(mock_kube_crud):
    """Verify the Chart.js compatible output format."""
    cursor = MagicMock()
    mock_kube_crud["cpu"].return_value = [(date(2024,1,1), "ns-a", 1.0)]
    mock_kube_crud["mem"].return_value = []
    
    res = get_daily_namespace_allocation(
        cursor, 1, base_date=None,
        daily_cluster_costs={"2024-01-01": 50.0},
        start_date=date(2024,1,1), end_date=date(2024,1,2),
        return_ui_format=True
    )
    
    assert "labels" in res
    assert "datasets" in res
    assert res["labels"] == ["2024-01-01"]
    assert res["datasets"][0]["label"] == "ns-a"
    assert res["datasets"][0]["data"] == [35.0] # 50 * 0.7 * 1.0
