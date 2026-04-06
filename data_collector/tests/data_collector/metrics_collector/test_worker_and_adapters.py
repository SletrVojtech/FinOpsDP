import pytest
from unittest.mock import MagicMock, patch
from metrics_collector.run_collection import CustodianAccountWorker
from metrics_collector.message_adapters import AdapterFactory, BaseCloudAdapter

class MockAdapter(BaseCloudAdapter):
    def get_provider(self): return "mock"
    def get_resource_id(self): return "id1"
    def get_resource_type(self): return "type1"
    def get_resource_name(self): return "name1"
    def get_billing_account_id(self): return "acc1"
    def get_metric_name(self): return "cpu"
    def get_region_name(self): return "reg1"
    def get_tags(self): return {}
    def get_datapoints(self): return []

def test_adapter_factory_registration():
    """Verify that adapters can be registered and retrieved."""
    AdapterFactory.register("test_provider", "test_res")(MockAdapter)
    
    adapter = AdapterFactory.create("test_provider", "test_res", {"raw": "data"})
    assert isinstance(adapter, MockAdapter)
    
    # Test normalization (stripping cloud prefix)
    adapter2 = AdapterFactory.create("test_provider", "provider.test_res", {"raw": "data"})
    assert isinstance(adapter2, MockAdapter)

def test_adapter_factory_fallback():
    """Verify fallback to 'default' adapter for unknown types."""
    AdapterFactory.register("test_provider", "default")(MockAdapter)
    
    # 'unknown_type' doesn't exist, should use 'default'
    adapter = AdapterFactory.create("test_provider", "unknown_type", {"raw": "data"})
    assert isinstance(adapter, MockAdapter)

@patch("metrics_collector.run_collection.RabbitMQClient")
@patch("metrics_collector.run_collection.PolicyLoader")
def test_custodian_worker_execution(mock_loader, mock_rmq):
    """Test the full worker pipeline."""
    # Setup mocks
    account = {"name": "acc", "provider": "aws", "account_id": "123"}
    region = "us-east-1"
    policy_data = {"policies": [{"name": "p1"}]}
    
    # Mock PolicyLoader to return a list with one mock policy
    mock_policy = MagicMock()
    mock_policy.name = "p1"
    mock_policy.resource_type = "aws.ec2"
    mock_policy.return_value = [{"InstanceId": "i-123"}]
    mock_policy.data = {"mode": {"type": "pull"}}
    
    mock_loader_instance = mock_loader.return_value
    mock_loader_instance.load_data.return_value.filter.return_value = [mock_policy]
    
    # Mock RMQ
    mock_rmq_instance = mock_rmq.return_value.__enter__.return_value
    
    worker = CustodianAccountWorker(account, region, policy_data, "/tmp", "PT5M")
    
    # Act
    counts, success = worker.run()
    
    # Assert
    assert success is True
    assert counts["p1"] == 1
    assert mock_rmq_instance.publish.called

@patch("metrics_collector.run_collection.PolicyLoader")
def test_custodian_worker_policy_failure(mock_loader):
    """Verify that one policy failing doesn't stop the whole worker."""
    account = {"name": "acc", "provider": "aws", "account_id": "123"}
    
    p1 = MagicMock()
    p1.name = "p1"
    p1.side_effect = Exception("Policy Crash")
    
    p2 = MagicMock()
    p2.name = "p2"
    p2.return_value = []
    
    mock_loader.return_value.load_data.return_value.filter.return_value = [p1, p2]
    
    worker = CustodianAccountWorker(account, "us-east-1", {"policies": []}, "/tmp", "PT5M")
    
    # We bypass RMQ for this test or mock it
    with patch("metrics_collector.run_collection.RabbitMQClient"):
        counts, success = worker.run()
    
    # Should still be success because p2 finished
    assert success is True
    assert "p1" not in counts
    assert "p2" in counts
