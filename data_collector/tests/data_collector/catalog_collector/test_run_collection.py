import pytest
from unittest.mock import MagicMock, patch
from catalog_collector.message import PricingRecord, HardwareRecord
from catalog_collector.run_collection import deduplicate_pricing_records, run_catalog_collector

def test_deduplicate_pricing_records():
    # Arrange
    # Create 2 records with the same primary key (cloud,sku,region, os)
    rec1 = PricingRecord(cloud="aws", instance_type="t3.micro", region="us-east-1", os="Linux", hourly_price_usd=0.010)
    rec2 = PricingRecord(cloud="aws", instance_type="t3.micro", region="us-east-1", os="Linux", hourly_price_usd=0.008) # expected variant
    rec3 = PricingRecord(cloud="aws", instance_type="t3.large", region="us-east-1", os="Linux", hourly_price_usd=0.050)

    records = [rec1, rec2, rec3]

    # Act
    deduplicated = deduplicate_pricing_records(records)

    # Assert
    assert len(deduplicated) == 2
    
    # Check the price
    t3_micro_record = next(r for r in deduplicated if r.instance_type == "t3.micro")
    assert t3_micro_record.hourly_price_usd == 0.008

@patch('catalog_collector.run_collection.RabbitMQClient')
@patch('catalog_collector.run_collection.DefaultAzureCredential')
@patch('catalog_collector.run_collection.AWSHardwareDownloader')
@patch('catalog_collector.run_collection.AWSPricingDownloader')
@patch('catalog_collector.run_collection.AzureHardwareDownloader')
@patch('catalog_collector.run_collection.AzurePricingDownloader')
def test_run_catalog_collector_batching(
    mock_azure_pricing, mock_azure_hw, mock_aws_pricing, mock_aws_hw, 
    mock_credential, mock_rmq_client
):
    # Arrange: Check records batching.
    fake_pricing_records = [
        PricingRecord(cloud="azure", instance_type=f"vm_{i}", region="weu", os="Linux", hourly_price_usd=0.1)
        for i in range(2500)
    ]
    mock_azure_pricing.return_value.fetch_pricing.return_value = fake_pricing_records

    mock_aws_pricing.return_value.fetch_pricing.return_value = []
    
    mock_rmq_instance = mock_rmq_client.return_value.__enter__.return_value

    # Act
    run_catalog_collector()

    # Assert
    # For 2500 records, with a batch size of 1000, publish should be called 3 times.
    assert mock_rmq_instance.publish.call_count == 3