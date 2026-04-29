import pytest
from unittest.mock import MagicMock, patch
from services.downsizing import evaluate_downsizing

@pytest.fixture
def mock_crud(mocker):
    return {
        "get_instance_metadata": mocker.patch("crud.downsizing.get_instance_metadata"),
        "get_telemetry": mocker.patch("crud.downsizing.get_telemetry"),
        "get_suitable_candidates": mocker.patch("crud.downsizing.get_suitable_candidates"),
        "get_actual_daily_cost": mocker.patch("crud.downsizing.get_actual_daily_cost"),
        "get_catalog_hourly_price": mocker.patch("crud.downsizing.get_catalog_hourly_price"),
    }

def test_evaluate_downsizing_zero_target_guard(mock_crud):
    """Verify that zero targets don't cause division by zero."""
    cursor = MagicMock()
    mock_crud["get_instance_metadata"].return_value = {
        "vcpu": 4, "memory_gb": 16, "provider": "aws", "region": "us-east-1", "os": "linux", "instance_type": "m5.xlarge",
        "architecture": "x86_64", "is_gpu": False, "is_confidential": False, "has_local_storage": False, "supports_premium_storage": True
    }
    mock_crud["get_telemetry"].return_value = {"cpu_p95": 10.0, "ram_max": 2.0}
    mock_crud["get_suitable_candidates"].return_value = []
    
    # Should not raise ZeroDivisionError
    res = evaluate_downsizing(cursor, 1, target_cpu_util=0.0)
    assert res["status"] == "success"

@pytest.mark.skip(reason="Skipping due to exchange rate API")
def test_evaluate_downsizing_zero_actual_cost(mock_crud):
    """Test behavior when actual_daily_cost is 0."""
    cursor = MagicMock()
    mock_crud["get_instance_metadata"].return_value = {
        "vcpu": 4, "memory_gb": 16, "provider": "aws", "region": "us-east-1", "os": "linux", "instance_type": "m5.xlarge",
        "architecture": "x86_64", "is_gpu": False, "is_confidential": False, "has_local_storage": False, "supports_premium_storage": True
    }
    mock_crud["get_telemetry"].return_value = {"cpu_p95": 1.0, "ram_max": 1.0}
    mock_crud["get_suitable_candidates"].return_value = [
        {"instance_type": "t3.medium", "hourly_price_usd": 0.02}
    ]
    mock_crud["get_catalog_hourly_price"].return_value = 0.20 # Current price
    mock_crud["get_actual_daily_cost"].return_value = 0.0 # actual cost is zero
    
    res = evaluate_downsizing(cursor, 1)
    
    assert res["status"] == "success"
    assert res["financials"]["current_actual_daily_cost_usd"] == 0.0
    assert res["financials"]["projected_daily_cost_usd"] == 0.0
    assert res["financials"]["estimated_monthly_savings_usd"] == 0.0

def test_evaluate_downsizing_no_catalog_price(mock_crud):
    """Test behavior when current catalog price is missing."""
    cursor = MagicMock()
    mock_crud["get_instance_metadata"].return_value = {
        "vcpu": 4, "memory_gb": 16, "provider": "aws", "region": "us-east-1", "os": "linux", "instance_type": "m5.xlarge",
        "architecture": "x86_64", "is_gpu": False, "is_confidential": False, "has_local_storage": False, "supports_premium_storage": True
    }
    mock_crud["get_telemetry"].return_value = {"cpu_p95": 1.0, "ram_max": 1.0}
    mock_crud["get_suitable_candidates"].return_value = [{"instance_type": "t3.medium", "hourly_price_usd": 0.02}]
    
    mock_crud["get_catalog_hourly_price"].return_value = None
    
    res = evaluate_downsizing(cursor, 1)
    
    assert res["status"] == "success"
    assert res["action"] == "downsize_recommended"
    assert "warning" in res
    assert "financials" not in res

def test_evaluate_downsizing_no_cheaper_candidates(mock_crud):
    """Test behavior when all candidates are more expensive."""
    cursor = MagicMock()
    mock_crud["get_instance_metadata"].return_value = {
        "vcpu": 4, "memory_gb": 16, "provider": "aws", "region": "us-east-1", "os": "linux", "instance_type": "m5.xlarge",
        "architecture": "x86_64", "is_gpu": False, "is_confidential": False, "has_local_storage": False, "supports_premium_storage": True
    }
    mock_crud["get_telemetry"].return_value = {"cpu_p95": 1.0, "ram_max": 1.0}
    
    # candidate exists but is more expensive
    mock_crud["get_suitable_candidates"].return_value = [
        {"instance_type": "expensive.gen", "hourly_price_usd": 1.0}
    ]
    mock_crud["get_catalog_hourly_price"].return_value = 0.20 # Current is 0.20
    
    res = evaluate_downsizing(cursor, 1)
    
    assert res["status"] == "success"
    assert res["action"] == "none"
    assert "nejlevnější dostupnou" in res["message"]
