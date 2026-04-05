import pytest
from unittest.mock import MagicMock, patch
from db_loader.catalog_processor import CatalogProcessor

@pytest.fixture
def mock_db():
    return MagicMock()

def test_catalog_processor_hardware_only(mock_db):
    # Arrange
    envelope = MagicMock()
    # Expect dict of HardwareRecord and PricingRecord
    envelope.payload = {
        'hardware_records': [
            {
                'cloud': 'AWS',
                'instance_type': 'T2.MICRO',
                'instance_family': 'T2',
                'vcpu': 1,
                'memory_gb': 1.0,
                'baseline_iops': 100,
                'baseline_throughput_mbps': 50.0,
                'network_performance': 'Low'
            }
        ],
        'pricing_records': []
    }

    processor = CatalogProcessor(mock_db)

    # Act
    with patch('db_loader.catalog_processor.execute_values') as mock_exec:
        processor.process(envelope)

    # Assert
    mock_exec.assert_called_once()
    
    # Check the mapping and toLower()
    args = mock_exec.call_args[0]
    values_list = args[2]
    
    assert len(values_list) == 1
    # cloud, instance_type.lower(), instance_family.lower(), vcpu, memory_gb, iops, throughput, perf, arch, gpu, confidential, local, premium
    assert values_list[0] == ('AWS', 't2.micro', 't2', 1, 1.0, 100, 50.0, 'Low', 'x86_64', False, False, False, False)

def test_catalog_processor_pricing_only(mock_db):
    # Arrange
    envelope = MagicMock()
    envelope.payload = {
        'hardware_records': [],
        'pricing_records': [
            {
                'cloud': 'Azure',
                'instance_type': 'Standard_D2s_v3',
                'region': 'WestEurope',
                'os': 'WINDOWS',
                'hourly_price_usd': 0.156
            }
        ]
    }

    processor = CatalogProcessor(mock_db)

    # Act
    with patch('db_loader.catalog_processor.execute_values') as mock_exec:
        processor.process(envelope)

    # Assert
    mock_exec.assert_called_once()
    
    
    # Check data trasformation
    args = mock_exec.call_args[0]
    values_list = args[2]
    
    assert len(values_list) == 1
    # All strings need to be lowercased
    assert values_list[0] == ('azure', 'standard_d2s_v3', 'westeurope', 'windows', 0.156)

def test_catalog_processor_both_records(mock_db):
    # Arrange
    envelope = MagicMock()
    envelope.payload = {
        'hardware_records': [{'cloud': 'aws', 'instance_type': 't3.nano', 'instance_family': 't3', 'vcpu': 2, 'memory_gb': 0.5}],
        'pricing_records': [{'cloud': 'aws', 'instance_type': 't3.nano', 'region': 'us-east-1', 'os': 'linux', 'hourly_price_usd': 0.005}]
    }

    processor = CatalogProcessor(mock_db)

    # Act
    with patch('db_loader.catalog_processor.execute_values') as mock_exec:
        processor.process(envelope)

    # Assert
    # execute_values called once for HW and once for pricing
    assert mock_exec.call_count == 2