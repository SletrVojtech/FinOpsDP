import pytest
from services.downsizing import evaluate_downsizing
from unittest.mock import MagicMock

def test_evaluate_downsizing_resource_not_found(mocker):
    mock_cursor = MagicMock()
    mock_get_metadata = mocker.patch("crud.downsizing.get_instance_metadata")
    mock_get_metadata.return_value = None
    
    result = evaluate_downsizing(mock_cursor, 1)
    
    assert result["status"] == "error"
    assert result["message"] == "Instance nenalezena"

def test_evaluate_downsizing_no_candidates(mocker):
    mock_cursor = MagicMock()
    
    # Current instance: 4 vCPU, 16 GB RAM
    mocker.patch("crud.downsizing.get_instance_metadata", return_value={
        "provider": "aws", "region": "eu-central-1", "os": "linux", "instance_type": "t3.xlarge", 
        "vcpu": 4, "memory_gb": 16, "architecture": "x86_64", "is_gpu": False, 
        "is_confidential": False, "has_local_storage": False, "supports_premium_storage": True
    })
    
    # Telemetry: 10% CPU, 20% RAM (should downsize)
    mocker.patch("crud.downsizing.get_telemetry", return_value={
        "cpu_p95": 10.0, "ram_max": 20.0, "disk_read_max": 0, "disk_write_max": 0, "net_in_max": 0, "net_out_max": 0
    })
    
    # No smaller candidates fit
    mocker.patch("crud.downsizing.get_suitable_candidates", return_value=[])
    
    result = evaluate_downsizing(mock_cursor, 1)
    
    assert result["status"] == "success"
    assert "žádná menší instance" in result["message"].lower()

@pytest.mark.skip(reason="Skipping due to exchange rate API")
def test_evaluate_downsizing_recommendation(mocker):
    mock_cursor = MagicMock()
    
    # Current: 4 vCPU, 16 GB, $1.0 hourly catalog price
    mocker.patch("crud.downsizing.get_instance_metadata", return_value={
        "provider": "aws", "region": "eu-central-1", "os": "linux", "instance_type": "t3.xlarge", 
        "vcpu": 4, "memory_gb": 16, "architecture": "x86_64", "is_gpu": False, 
        "is_confidential": False, "has_local_storage": False, "supports_premium_storage": True
    })
    
    mocker.patch("crud.downsizing.get_telemetry", return_value={
        "cpu_p95": 12.0, "ram_max": 4.0, "disk_read_max": 0, "disk_write_max": 0, "net_in_max": 0, "net_out_max": 0
    })
    
    # Target vCPU = 4 * (12/60) = 0.8 -> round to 1.0
    # Target RAM = 16 * (4/80) = 0.8 -> round to 1.0
    
    # Candidate: 1 vCPU, 2 GB, $0.2 hourly price (80% savings)
    mocker.patch("crud.downsizing.get_suitable_candidates", return_value=[
        {"instance_type": "t3.micro", "hourly_price_usd": 0.2}
    ])
    
    mocker.patch("crud.downsizing.get_actual_daily_cost", return_value=12.0)
    mocker.patch("crud.downsizing.get_catalog_hourly_price", return_value=1.0)
    
    result = evaluate_downsizing(mock_cursor, 1)
    
    assert result["status"] == "success"
    assert result["action"] == "downsize_recommended"
    assert result["recommended_instance"] == "t3.micro"
    # savings_percentage = (1.0 - 0.2) / 1.0 = 0.8 -> 80%
    assert result["financials"]["savings_percentage"] == 80.0
    # projected cost = 12.0 * (1 - 0.8) = 2.40
    assert result["financials"]["projected_daily_cost_usd"] == 2.40
    # monthly savings = (12.0 - 2.40) * 30 = 288.0
    assert result["financials"]["estimated_monthly_savings_usd"] == 288.0
