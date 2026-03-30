import pytest
from krr_collector.message import KRRRecommendationPayload, KRRBatchPayload

def test_krr_recommendation_payload():
    # Act
    payload = KRRRecommendationPayload(
        cloud_provider="azure",
        account_id="sub-123",
        cluster_name="aks-test",
        cluster_id="id-123",
        resource_id="id-123:namespace/default:Deployment/app",
        namespace="default",
        workload_type="Deployment",
        workload_name="app",
        container_name="app-container",
        current_cpu_request="100m",
        recommended_cpu_request="50m"
    )

    # Assert
    assert payload.cloud_provider == "azure"
    assert payload.current_cpu_request == "100m"
    assert payload.recommended_cpu_request == "50m"
    assert payload.current_memory_request is None
    assert payload.recommended_memory_request is None

def test_krr_batch_payload():
    rec = KRRRecommendationPayload(
        cloud_provider="aws", account_id="123", cluster_name="eks",
        cluster_id="id", resource_id="res", namespace="ns",
        workload_type="Deploy", workload_name="w", container_name="c"
    )
    
    batch = KRRBatchPayload(recommendations=[rec])
    assert len(batch.recommendations) == 1
    assert batch.recommendations[0].cloud_provider == "aws"