import pytest
from unittest.mock import MagicMock, patch, mock_open
from kube_collector.kube_collector import KubePrometheusCollector
import json

MOCK_YAML_CONFIG = """
clusters:
  - provider: aws
    account_id: "111122223333"
    cluster_name: my-eks-cluster
    cluster_resource_id: arn:aws:eks:eu-central-1:111122223333:cluster/my-eks-cluster
    context: arn:aws:eks:eu-central-1:111122223333:cluster/my-eks-cluster
    prometheus:
      namespace: monitoring
      service_name: prometheus-k8s
      port: 9090
"""

@pytest.fixture
def collector():
    # Mock the config file loading
    with patch('builtins.open', mock_open(read_data=MOCK_YAML_CONFIG)):
        return KubePrometheusCollector(config_path="dummy.yml", hours_back=1)

def test_format_to_payload(collector):
    # Arrange: Prometheus data
    mock_prom_data = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {
                        "namespace": "kube-system",
                        "label_app": "coredns", # Prefix 'label_' should be removed
                        "pod": "coredns-123"
                    },
                    "values": [
                        [1704067200, "1.5"], # Timestamp, Value
                        [1704070800, "2.0"]
                    ]
                }
            ]
        }
    }

    # Act
    messages = collector._format_to_payload(
        prom_data=mock_prom_data,
        provider="aws",
        account_id="111122223333",
        cluster_name="my-eks-cluster",
        cluster_id="cluster-urn",
        metric_name="cpu_requests_cores"
    )

    # Assert
    assert len(messages) == 1
    msg = messages[0]
    
    # Get payload from IngestionMessage
    payload = msg.payload
    assert payload["resource_name"] == "kube-system"
    assert payload["resource_id"] == "cluster-urn:namespace/kube-system"
    assert payload["metric_name"] == "cpu_requests_cores"
    
    # Check parsed tags - 
    tags = payload["tags"]
    assert tags["cluster"] == "my-eks-cluster"
    assert tags["app"] == "coredns" # label_app
    assert tags["namespace"] == "kube-system"
    
    # DPs
    assert len(payload["datapoints"]) == 2
    assert payload["datapoints"][0]["value"] == 1.5
    assert payload["datapoints"][0]["timestamp"] == 1704067200

@patch('kube_collector.kube_collector.config')
@patch('kube_collector.kube_collector.client')
def test_process_cluster(mock_client, mock_config, collector):
    # Arrange
    cluster_config = collector.config['clusters'][0]
    
    # Mocking K8s API
    mock_api_client = MagicMock()
    mock_config.new_client_from_config.return_value = mock_api_client
    
    mock_v1 = MagicMock()
    mock_client.CoreV1Api.return_value = mock_v1
    
    # Prometheus proxy response
    mock_v1.api_client.call_api.return_value = {
        "data": {
            "result": [
                {
                    "metric": {"namespace": "default"},
                    "values": [[1000, "1.0"]]
                }
            ]
        }
    }

    # Act
    messages = collector._process_cluster(cluster_config)

    # Assert config.new_client_from_config with correct context
    mock_config.new_client_from_config.assert_called_once_with(context="arn:aws:eks:eu-central-1:111122223333:cluster/my-eks-cluster")
    
    # 2 collected metrics
    assert mock_v1.api_client.call_api.call_count == 2
    
    # Check the API params
    args, kwargs = mock_v1.api_client.call_api.call_args_list[0]
    path_params = kwargs['path_params']
    assert path_params['namespace'] == 'monitoring'
    assert path_params['name'] == 'http:prometheus-k8s:9090'
    assert path_params['path'] == 'api/v1/query_range'
    
    # 2 IMs for 2 metrics
    assert len(messages) == 2