import pytest
from krr_collector.krr_parser import KRRFileParser

@pytest.fixture
def cluster_info():
    return {
        'provider': 'azure',
        'account_id': 'sub-123',
        'cluster_resource_id': '/subscriptions/sub-123/rg/aks',
        'cluster_name': 'aks-test'
    }

def test_krr_parser_valid_json(cluster_info):
    # Arrange: 
    mock_krr_data = {
        "scans": [
            {
                "object": {
                    "namespace": "backend",
                    "name": "api-server",
                    "kind": "Deployment",
                    "container": "api-container",
                    "allocations": {
                        "requests": {"cpu": "200m", "memory": "512Mi"}
                    }
                },
                "recommended": {
                    "requests": {
                        "cpu": {"value": "100m", "severity": "WARNING"},
                        "memory": {"value": "256Mi", "severity": "OK"}
                    }
                }
            },
            {
                # Object without namespace, should be skipped
                "object": {
                    "name": "cluster-agent",
                    "kind": "DaemonSet"
                }
            }
        ]
    }

    parser = KRRFileParser(krr_data=mock_krr_data, cluster_info=cluster_info)

    # Act
    messages = parser.parse_to_rabbitmq()

    # Assert
    assert len(messages) == 1
    msg = messages[0]
    
    assert msg.source_module == "krr_collector"
    
    # List of reccomendations as a payload
    recommendations = msg.payload["recommendations"]
    assert len(recommendations) == 1
    
    rec = recommendations[0]
    assert rec["namespace"] == "backend"
    assert rec["current_cpu_request"] == "200m"
    assert rec["recommended_cpu_request"] == "100m"
    # URN generation
    assert rec["resource_id"] == "/subscriptions/sub-123/rg/aks:namespace/backend:Deployment/api-server:container/api-container"

def test_krr_parser_empty_data(cluster_info):
    # Returned [] upon empty KRR response
    parser = KRRFileParser(krr_data={}, cluster_info=cluster_info)
    assert parser.parse_to_rabbitmq() == []