import pytest
from unittest.mock import MagicMock, patch
from catalog_collector.hardware_collector import AzureHardwareDownloader, AWSHardwareDownloader

@patch('catalog_collector.hardware_collector.requests.get')
def test_azure_hardware_downloader(mock_requests_get):
    # Arrange
    downloader = AzureHardwareDownloader(subscription_id="sub-123", access_token="token")
    
    # Simulated Azure SKU API response with other instances than VMs
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'value': [
            {
                'resourceType': 'virtualMachines',
                'name': 'Standard_D2s_v3',
                'family': 'standardDSv3Family',
                'capabilities': [
                    {'name': 'vCPUs', 'value': '2'},
                    {'name': 'MemoryGB', 'value': '8.0'},
                    {'name': 'UncachedDiskIOPS', 'value': '3200'},
                    {'name': 'UncachedDiskBytesPerSecond', 'value': '104857600'} # 100 MB/s
                ]
            },
            {
                'resourceType': 'disks', # Should be skipped
                'name': 'Standard_LRS'
            }
        ],
        'nextLink': None
    }
    mock_requests_get.return_value = mock_response

    # Act
    records = downloader.fetch_hardware()

    # Assert
    assert len(records) == 1
    rec = records[0]
    assert rec.cloud == "azure"
    assert rec.instance_type == "Standard_D2s_v3"
    assert rec.vcpu == 2
    assert rec.memory_gb == 8.0
    assert rec.baseline_throughput_mbps == 100.0 # 104857600 / 1024 / 1024

@patch('catalog_collector.hardware_collector.boto3.client')
def test_aws_hardware_downloader(mock_boto_client):
    # Arrange
    mock_ec2 = MagicMock()
    mock_boto_client.return_value = mock_ec2
    
    mock_paginator = MagicMock()
    # 2 instaces, different throughput format "10 Gigabit", "Up to 5 Gigabit"
    mock_paginator.paginate.return_value = [{
        'InstanceTypes': [
            {
                'InstanceType': 't3.micro',
                'VCpuInfo': {'DefaultVCpus': 2},
                'MemoryInfo': {'SizeInMiB': 1024},
                'NetworkInfo': {'NetworkPerformance': 'Up to 5 Gigabit'}
            },
            {
                'InstanceType': 'm5.large',
                'VCpuInfo': {'DefaultVCpus': 2},
                'MemoryInfo': {'SizeInMiB': 8192},
                'NetworkInfo': {'NetworkPerformance': '10 Gigabit'}
            }
        ]
    }]
    mock_ec2.get_paginator.return_value = mock_paginator
    
    downloader = AWSHardwareDownloader()

    # Act
    records = downloader.fetch_hardware()

    # Assert
    assert len(records) == 2
    
    t3 = records[0]
    assert t3.instance_type == "t3.micro"
    assert t3.instance_family == "t3"
    assert t3.memory_gb == 1.0 # 1024 MiB / 1024
    assert t3.network_performance == "5000.0"
    
    m5 = records[1]
    assert m5.network_performance == "10000.0"