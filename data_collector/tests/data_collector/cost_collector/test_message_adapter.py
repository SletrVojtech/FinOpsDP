import pytest
from datetime import datetime
from cost_collector.message_adapter import FocusCostAdapter

def test_focus_cost_adapter_aws():
    # Arrange: Row returned by DuckDB for AWS
    aws_row = {
        'ProviderName': 'Amazon Web Services',
        'SubAccountId': '111122223333',
        'resource_id': 'arn:aws:ec2:eu-central-1:111122223333:instance/i-12345',
        'RegionId': 'eu-central-1',
        'ResourceName': 'prod-web',
        'ResourceType': 'EC2 Instance',
        'ServiceName': 'AmazonEC2',
        'ServiceCategory': 'Compute',
        'SkuPriceId': 'sku-abc',
        'charge_period_start': datetime(2024, 1, 1),
        'charge_period_end': datetime(2024, 1, 2),
        'billed_cost': 15.50,
        'BillingCurrency': 'USD',
        'Tags': '{"env": "prod"}'
    }

    # Act
    adapter = FocusCostAdapter(aws_row)
    payload = adapter.to_payload()

    # Assert
    assert payload.provider == 'aws'
    assert payload.account_id == '111122223333'
    assert payload.resource_id == 'arn:aws:ec2:eu-central-1:111122223333:instance/i-12345'
    assert payload.tags == {"env": "prod"}
    assert payload.billed_cost == 15.50

def test_focus_cost_adapter_azure():
    # Arrange: Row returned by DuckDB for Azure
    azure_row = {
        'ProviderName': 'Microsoft Azure',
        'SubAccountId': '/subscriptions/abc-123-def',
        'resource_id': '/subscriptions/abc-123-def/rg/vm1',
        'RegionId': 'westeurope',
        'charge_period_start': datetime(2024, 1, 1),
        'charge_period_end': datetime(2024, 1, 2),
        'billed_cost': 10.0,
        'Tags': None 
    }

    # Act
    adapter = FocusCostAdapter(azure_row)
    payload = adapter.to_payload()

    # Assert
    assert payload.provider == 'azure'
    # Parse the subscription
    assert payload.account_id == 'abc-123-def' 
    assert payload.tags == {} # None tags -> {}