import pytest
from crud.downsizing import get_instance_metadata, get_telemetry, get_catalog_hourly_price
from unittest.mock import MagicMock

def test_get_instance_metadata(mock_cursor):
    # 11 columns: provider, region, os, type, vcpu, mem, arch, gpu, confidential, local, premium
    mock_cursor.fetchone.return_value = ("aws", "us-east-1", "linux", "t3.medium", 2, 4.0, "x86_64", False, False, False, True)
    
    metadata = get_instance_metadata(mock_cursor, 123)
    
    assert metadata["instance_type"] == "t3.medium"
    assert metadata["vcpu"] == 2
    assert "WHERE e.Id = %(resource_id)s" in mock_cursor.execute.call_args[0][0]
    assert mock_cursor.execute.call_args[0][1] == {"resource_id": 123}

def test_get_telemetry(mock_cursor):
    # Mocking 6 resulting columns
    mock_cursor.fetchone.return_value = (10.5, 2048.0, 100.0, 50.0, 1000.0, 500.0)
    
    telemetry = get_telemetry(mock_cursor, 123, 14)
    
    assert telemetry["cpu_p95"] == 10.5
    assert telemetry["ram_max"] == 2048.0
    assert "FROM metrics" in mock_cursor.execute.call_args[0][0] # for <= 14 days

def test_get_catalog_hourly_price_found(mock_cursor):
    mock_cursor.fetchone.return_value = (0.05,)
    
    price = get_catalog_hourly_price(mock_cursor, "aws", "us-east-1", "linux", "t3.micro")
    
    assert price == 0.05
    assert "FROM pricingcatalog" in mock_cursor.execute.call_args[0][0]

def test_get_catalog_hourly_price_not_found(mock_cursor):
    mock_cursor.fetchone.return_value = None
    
    price = get_catalog_hourly_price(mock_cursor, "unknown", "reg", "os", "type")
    
    assert price is None
