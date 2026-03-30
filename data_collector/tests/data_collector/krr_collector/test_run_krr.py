import pytest
import json
import subprocess
from unittest.mock import MagicMock, patch, mock_open
from run_krr import run_krr_for_context, main

def test_run_krr_for_context_success():
    # Arrange
    fake_json_output = '{"scans": [{"object": {"name": "test"}}]}'
    mock_result = MagicMock()
    mock_result.stdout = fake_json_output
    
    # Act
    with patch('run_krr.subprocess.run', return_value=mock_result) as mock_run:
        result = run_krr_for_context("my-k8s-context")

    # Assert
    mock_run.assert_called_once()
    assert result == {"scans": [{"object": {"name": "test"}}]}

def test_run_krr_for_context_subprocess_error():
    # Arrange: Simulate docker failure
    mock_error = subprocess.CalledProcessError(returncode=1, cmd="docker", stderr="Docker not found")
    
    # Act
    with patch('run_krr.subprocess.run', side_effect=mock_error):
        result = run_krr_for_context("my-k8s-context")

    # Assert
    assert result is None

MOCK_CLUSTER_CONFIG = """
clusters:
  - provider: aws
    context: arn:aws:eks:eu-central-1:111122223333:cluster/my-cluster
    account_id: '123'
    cluster_name: 'test'
"""

@patch('run_krr.RabbitMQClient')
@patch('run_krr.KRRFileParser')
@patch('run_krr.run_krr_for_context')
def test_main_success(mock_run_krr, mock_parser_class, mock_rmq_client):
    # Arrange
    # Mocked load from kubeconfig
    mock_file = mock_open(read_data=MOCK_CLUSTER_CONFIG)
    
    # Mocked KRR response
    mock_run_krr.return_value = {"fake": "krr_data"}
    
    # Mocked parser to return 1 message
    mock_parser_instance = mock_parser_class.return_value
    mock_msg = MagicMock()
    mock_msg.model_dump_json.return_value = '{"rabbitmq": "message"}'
    mock_parser_instance.parse_to_rabbitmq.return_value = [mock_msg]
    
    # Mock RMQ
    mock_rmq_instance = mock_rmq_client.return_value.__enter__.return_value

    # Act
    with patch('builtins.open', mock_file):
        main()

    # Assert - check the used context
    mock_run_krr.assert_called_once_with(context_name="arn:aws:eks:eu-central-1:111122223333:cluster/my-cluster")
    
    # Check the parser calls
    mock_parser_class.assert_called_once()
    mock_parser_instance.parse_to_rabbitmq.assert_called_once()
    
    # Check the RabbitMQ queue
    mock_rmq_instance.publish.assert_called_once_with(
        queue_name="data_ingestion",
        message='{"rabbitmq": "message"}'
    )