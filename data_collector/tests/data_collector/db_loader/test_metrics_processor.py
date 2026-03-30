import pytest
from unittest.mock import MagicMock, patch
from db_loader.metrics_processor import MetricsProcessor

@pytest.fixture
def mock_db():
    db_conn = MagicMock()
    cursor = db_conn.cursor.return_value
    
    # Simulate fetchone call
    cursor.fetchone.return_value = [42]
    return db_conn

def test_metrics_processor_aws_pipeline(mock_db):
    # Simulated data for aws.EC2
    mock_envelope = MagicMock()
    mock_envelope.payload = {
        "provider": "aws",
        "resource_id": "i-0abcd1234efgh5678",
        "billing_account_id": "111122223333",
        "resource_name": "Prod-Web-Server",
        "resource_type": "aws.ec2",
        "metric_name": "aws_ec2_cpu_usage_avg",
        "metric_period": 5,
        "tags": {"env": "prod"},
        "extras": {"normalized_os": "Linux"},
        "datapoints": [
            {"timestamp": "2024-01-01T12:00:00+00:00", "value": 45.5}
        ]
    }
    
    processor = MetricsProcessor(mock_db)

    # Act
    with patch('db_loader.metrics_processor.execute_values') as mock_execute_values:
        processor.process(mock_envelope)

    # Assert for created entities
    cursor = mock_db.cursor.return_value
    
    # 2 calls for account and instance
    assert cursor.execute.call_count == 2
    
    # Check the account entity
    first_call_args = cursor.execute.call_args_list[0][0][1] # Tuple parametrů dotazu
    assert first_call_args[0] == "111122223333" # ExternalId (Account ID)
    assert first_call_args[2] == "aws_account"  # ResourceType
    
    # Check the instance entity
    second_call_args = cursor.execute.call_args_list[1][0][1]
    assert second_call_args[0] == "i-0abcd1234efgh5678" # ExternalId
    assert second_call_args[3] == 42 # ParentId

    # Assert for metrics
    mock_execute_values.assert_called_once()
    
    args, kwargs = mock_execute_values.call_args
    inserted_values = args[2] # data
    
    assert len(inserted_values) == 1
    # (EntityId, MetricType, Timestamp, Value, IntervalMinutes)
    # "_".join("aws_ec2_cpu_usage_avg".split("_")[1:]) -> ec2_cpu_usage_avg
    assert inserted_values[0] == (42, 'ec2_cpu_usage_avg', '2024-01-01T12:00:00+00:00', 45.5, 5)

def test_metrics_processor_azure_hierarchy(mock_db):
    # Check Azure hierarchy resolution
    mock_envelope = MagicMock()
    mock_envelope.payload = {
        "provider": "azure",
        "resource_id": "/subscriptions/sub-123/resourceGroups/rg1/providers/Microsoft.Compute/vm/vm1",
        "billing_account_id": "sub-123",
        "resource_name": "vm1",
        "resource_type": "azure.vm",
        "metric_name": "azure_cpu_avg",
        "metric_period": 5,
        "datapoints": [] # 0 execute_values calls expected
    }
    
    processor = MetricsProcessor(mock_db)

    with patch('db_loader.metrics_processor.execute_values') as mock_execute_values:
        processor.process(mock_envelope)

    # Assert
    cursor = mock_db.cursor.return_value
    
    # (Subscription, Resource Group, VM)
    assert cursor.execute.call_count == 3
    
    assert cursor.execute.call_args_list[0][0][1][0] == "/subscriptions/sub-123"
    
    assert cursor.execute.call_args_list[1][0][1][0] == "/subscriptions/sub-123/resourcegroups/rg1"
    
    # No metrics upsert called
    mock_execute_values.assert_not_called()