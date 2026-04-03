import pytest
from unittest.mock import MagicMock, patch
from db_loader.krr_processor import KRRProcessor
from datetime import datetime, timezone

@pytest.fixture
def mock_db():
    db_conn = MagicMock()
    # Returns incrementing ID for each call
    db_conn.cursor.return_value.fetchone.side_effect = [[1], [2], [3], [4], [5]]
    return db_conn

def test_krr_processor_uses_namespace_cache(mock_db):
    # Arrange
    envelope = MagicMock()
    envelope.payload = {}
    envelope.timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # 2 reccomendations for the same namespace
    rec1 = MagicMock()
    rec1.cloud_provider = "azure"
    rec1.account_id = "sub-123"
    rec1.cluster_id = "/subscriptions/sub-123/resourcegroups/rg1/providers/microsoft.containerservice/managedclusters/aks1"
    rec1.cluster_name = "aks1"
    rec1.namespace = "backend"
    rec1.workload_type = "Deployment"
    rec1.workload_name = "api-server"
    rec1.container_name = "node-app"
    rec1.current_cpu_request = 1.0
    rec1.recommended_cpu_request = 0.5
    rec1.current_memory_request = 1024
    rec1.recommended_memory_request = 512

    rec2 = MagicMock()
    rec2.cloud_provider = "azure"
    rec2.account_id = "sub-123"
    rec2.cluster_id = rec1.cluster_id
    rec2.cluster_name = "aks1"
    rec2.namespace = "backend"
    rec2.workload_type = "Deployment"
    rec2.workload_name = "worker"
    rec2.container_name = "python-worker"

    processor = KRRProcessor(mock_db)

    # Act
    with patch('db_loader.krr_processor.KRRBatchPayload.model_validate') as mock_validate:
        mock_validate.return_value.recommendations = [rec1, rec2]
        
        with patch('db_loader.krr_processor.execute_values') as mock_exec:
            processor.process(envelope)

    # Assert
    cursor = mock_db.cursor.return_value
    
    # Expectiong 4 calls for cursor.execute (Sub, RG, Cluster, NS)
    # More calls would indicate cache_set mapping to fail
    assert cursor.execute.call_count == 4
    
    # 1 call with 2 records
    mock_exec.assert_called_once()
    recommendations_values = mock_exec.call_args[0][2]
    assert len(recommendations_values) == 2
    
    # Both using the same ID
    assert recommendations_values[0][0] == recommendations_values[1][0]