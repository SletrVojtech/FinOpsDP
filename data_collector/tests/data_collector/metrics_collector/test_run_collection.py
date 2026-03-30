import pytest
from unittest.mock import patch, MagicMock
from metrics_collector.run_collection import run_account_in_memory

@patch("metrics_collector.run_collection.RabbitMQClient")
@patch("metrics_collector.run_collection.PolicyLoader")
def test_run_account_in_memory_success(mock_policy_loader, mock_rmq_client):
    # Arrange
    mock_account = {
        "name": "test-aws-account",
        "provider": "aws",
        "account_id": "111122223333"
    }
    mock_region = "eu-west-1"
    mock_policy_data = {"policies": [{"name": "test_policy", "resource": "aws.ec2"}]}
    
    # Mock Custodian policy execution to return 1 fake resource
    mock_policy_instance = MagicMock()
    mock_policy_instance.name = "test_policy"
    mock_policy_instance.resource_type = "aws.ec2"
    mock_policy_instance.return_value = [{"InstanceId": "i-mock123", "Tags": []}]
    mock_policy_instance.data = {"mode": {"type": "pull"}}
    
    mock_collection = [mock_policy_instance]
    mock_policy_loader.return_value.load_data.return_value.filter.return_value = mock_collection

    # Mock RabbitMQ
    mock_rmq_instance = mock_rmq_client.return_value.__enter__.return_value

    # Act
    with patch("metrics_collector.run_collection.environ") as mock_environ:
        counts, success = run_account_in_memory(
            account=mock_account,
            region=mock_region,
            policy_data=mock_policy_data,
            output_dir="/tmp/test",
            debug=True
        )

    # Assert
    assert success is True
    assert counts["test_policy"] == 1
    
    # Check that RabbitMQ.publish has been called
    assert mock_rmq_instance.publish.called
    
    # Check the send payload
    publish_args = mock_rmq_instance.publish.call_args[1]
    assert publish_args["queue_name"] == "data_ingestion"
    assert "source_module" in publish_args["message"]
    assert "custodian" in publish_args["message"]