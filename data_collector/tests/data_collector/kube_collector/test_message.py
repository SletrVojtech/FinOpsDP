import pytest
from pydantic import ValidationError
from kube_collector.message import Datapoint, KubeMetricsPayload

def test_datapoint_validation():
    # Act
    dp = Datapoint(timestamp=1704067200.0, value=2.5)
    
    # Assert
    assert dp.timestamp == 1704067200.0
    assert dp.value == 2.5

    # Type change to float
    dp_str = Datapoint(timestamp="1704067200", value="3.14")
    assert dp_str.timestamp == 1704067200.0
    assert dp_str.value == 3.14

def test_kube_metrics_payload_creation():
    # Arrange
    dp = Datapoint(timestamp=1704067200, value=1.0)
    
    # Act
    payload = KubeMetricsPayload(
        cloud_provider="aws",
        account_id="12345",
        resource_id="arn:aws:eks:cluster/my-cluster:namespace/kube-system",
        resource_name="kube-system",
        metric_name="cpu_requests_cores",
        tags={"cluster": "my-cluster"},
        datapoints=[dp]
    )

    # Assert
    assert payload.cloud_provider == "aws"
    assert payload.resource_type == "kubernetes_namespace" # Default value
    assert len(payload.datapoints) == 1
    assert payload.metric_period == 60 # Default value in minutes