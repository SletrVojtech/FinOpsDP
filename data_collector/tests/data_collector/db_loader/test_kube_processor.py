import pytest
from unittest.mock import MagicMock, patch
from db_loader.kube_processor import KubeProcessor
from datetime import datetime

@pytest.fixture
def mock_db():
    db_conn = MagicMock()
    db_conn.cursor.return_value.fetchone.return_value = [99] # Fake Entity ID
    return db_conn

def test_kube_processor_process(mock_db):
    # Arrange
    envelope = MagicMock()
    envelope.payload = {}

    # KubeMetrics row
    mock_dp = MagicMock()
    mock_dp.timestamp = 1704067200 # 2024-01-01 00:00:00
    mock_dp.value = 2.5

    mock_payload = MagicMock()
    mock_payload.cloud_provider = "aws"
    mock_payload.account_id = "111122223333"
    # cluster_id = cluster ARN + namespace
    mock_payload.resource_id = "arn:aws:eks:eu-central-1:111122223333:cluster/my-cluster:namespace/kube-system"
    mock_payload.resource_name = "kube-system"
    mock_payload.resource_type = "kubernetes_namespace"
    mock_payload.tags = {"cluster": "my-cluster"}
    mock_payload.metric_name = "cpu_usage"
    mock_payload.datapoints = [mock_dp]

    processor = KubeProcessor(mock_db)

    # Act
    with patch('db_loader.kube_processor.KubeMetricsPayload.model_validate', return_value=mock_payload):
        with patch('db_loader.kube_processor.execute_values') as mock_exec:
            processor.process(envelope)

    # Assert
    cursor = mock_db.cursor.return_value
    
    # 3 Entity calls - AWS acc, k8s cluster, namespace
    assert cursor.execute.call_count == 3
    
    cluster_args = cursor.execute.call_args_list[1][0][1]
    assert cluster_args[0] == "arn:aws:eks:eu-central-1:111122223333:cluster/my-cluster"
    assert cluster_args[3] == "kubernetes_cluster"
    
    # Check saved metrics
    mock_exec.assert_called_once()
    metric_values = mock_exec.call_args[0][2]
    assert len(metric_values) == 1
    
    # Entity ID, Timestamp, MetricName, Value, Tags
    assert metric_values[0][0] == 99
    assert metric_values[0][2] == "cpu_usage"
    assert metric_values[0][3] == 2.5