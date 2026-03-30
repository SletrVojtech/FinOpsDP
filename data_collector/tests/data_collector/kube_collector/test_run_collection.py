import pytest
from unittest.mock import MagicMock, patch
from kube_collector.run_collection import run_kube_collection

@patch('kube_collector.run_collection.os.path.exists')
@patch('kube_collector.run_collection.KubePrometheusCollector')
@patch('kube_collector.run_collection.RabbitMQClient')
def test_run_kube_collection_success(mock_rmq_client, mock_collector_class, mock_exists):
    # Arrange
    mock_exists.return_value = True
    
    # Mock a collector returning a message
    mock_collector = mock_collector_class.return_value
    mock_msg = MagicMock()
    mock_msg.model_dump_json.return_value = '{"fake": "json"}'
    mock_collector.collect_all.return_value = [mock_msg]

    # Mock RabbitMQClient
    mock_rmq_instance = mock_rmq_client.return_value.__enter__.return_value

    # Act
    run_kube_collection(config_path="dummy.yml", hours_back=1)

    # Assert
    mock_collector_class.assert_called_once_with(config_path="dummy.yml", hours_back=1)
    mock_collector.collect_all.assert_called_once()
    
    # Check the destination queue
    mock_rmq_instance.publish.assert_called_once_with(
        queue_name="data_ingestion",
        message='{"fake": "json"}'
    )

@patch('kube_collector.run_collection.os.path.exists')
def test_run_kube_collection_file_not_found(mock_exists):
    # Arrange
    mock_exists.return_value = False
    
    # Act - log an error when config not found
    with patch('kube_collector.run_collection.KubePrometheusCollector') as mock_collector:
        run_kube_collection(config_path="invalid.yml")
        
        # Assert
        mock_collector.assert_not_called()