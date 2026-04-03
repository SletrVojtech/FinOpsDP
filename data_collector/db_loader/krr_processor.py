import logging
from psycopg2.extras import execute_values
from pydantic import ValidationError
from datetime import datetime, timezone

from krr_collector.message import KRRBatchPayload
from db_loader.base_processor import BaseProcessor, register_processor

log = logging.getLogger('krr_processor')

@register_processor("krr_collector")
class KRRProcessor(BaseProcessor):
    """
    Parse KRR Recommendations from RabbitMQ into DB.
    Links recommendations to the Namespace entity.
    """

    def process(self, envelope):
        payload_dict = envelope.payload
        try:
            batch = KRRBatchPayload.model_validate(payload_dict)
        except ValidationError as e:
            log.error(f"Invalid KRRBatchPayload: {e}")
            raise

        if not batch.recommendations:
            return

        scan_timestamp = envelope.timestamp if hasattr(envelope, 'timestamp') else datetime.now(timezone.utc)

        values = []
        namespace_cache = {}

        for item in batch.recommendations:
            # Create an URN for the namespace and get ID
            namespace_urn = f"{item.cluster_id}:namespace/{item.namespace}".lower()

            if namespace_urn not in namespace_cache:
                entity_id = self._resolve_hierarchy(item, namespace_urn)
                namespace_cache[namespace_urn] = entity_id
            
            entity_id = namespace_cache[namespace_urn]

            # Add a line to the insert
            values.append((
                entity_id,
                scan_timestamp,
                item.workload_type,
                item.workload_name,
                item.container_name,
                item.current_cpu_request,
                item.recommended_cpu_request,
                item.current_memory_request,
                item.recommended_memory_request
            ))

        self._insert_recommendations(values)
        log.info(f"Saved {len(values)} recommendations to DB.")

    def _resolve_hierarchy(self, item, namespace_urn) -> int:
        """
        Creates hierarchy of entities on top of cloud providers.
        Returns entity ID for the NAMESPACE.
        """
        provider = item.cloud_provider
        acc_id = item.account_id.lower()
        cluster_id = item.cluster_id.lower()
        cluster_name = item.cluster_name.lower()

        parent_id = 0
        
        if provider == "azure":
            parent_id = self.resolve_azure_hierarchy(cluster_id)
                
        elif provider == "aws":
            parent_id = self.resolve_aws_hierarchy(acc_id)

        # UPSERT k8s cluster
        cluster_db_id = self.upsert_basic_entity(
            ext_id=cluster_id,
            provider=provider, 
            res_name=cluster_name, 
            res_type="kubernetes_cluster", 
            parent_id=parent_id
        )

        # UPSERT Namespace
        return self.upsert_basic_entity(
            ext_id=namespace_urn,
            provider=provider,
            res_name=item.namespace.lower(),
            res_type="kubernetes_namespace",
            parent_id=cluster_db_id
        )

    def _insert_recommendations(self, values: list):
        """Bulk UPSERT of latest recommendations into KubeRecommendations table"""
        query = """
            INSERT INTO KubeRecommendations (
                EntityId, Timestamp, WorkloadType, WorkloadName, ContainerName, 
                CurrentCpuRequest, RecommendedCpuRequest, CurrentMemoryRequest, RecommendedMemoryRequest
            )
            VALUES %s
            ON CONFLICT (EntityId, WorkloadType, WorkloadName, ContainerName) 
            DO UPDATE SET 
                Timestamp = EXCLUDED.Timestamp,
                CurrentCpuRequest = EXCLUDED.CurrentCpuRequest,
                RecommendedCpuRequest = EXCLUDED.RecommendedCpuRequest,
                CurrentMemoryRequest = EXCLUDED.CurrentMemoryRequest,
                RecommendedMemoryRequest = EXCLUDED.RecommendedMemoryRequest;
        """
        execute_values(self.cursor, query, values)