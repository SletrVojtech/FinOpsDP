"""
KRR Processor Module.

This module provides the KRRProcessor class, which handles the ingestion
of Kubernetes Resource Recommendations (from KRR) into the database.
"""

import logging
from datetime import datetime, timezone
from typing import Any, List, Dict, Tuple, Optional
from psycopg2.extras import execute_values
from pydantic import ValidationError

from krr_collector.message import KRRBatchPayload, KRRRecommendationPayload
from db_loader.base_processor import BaseProcessor, register_processor

log = logging.getLogger('krr_processor')


@register_processor("krr_collector")
class KRRProcessor(BaseProcessor):
    """
    Handles the ingestion of KRR recommendations for Kubernetes workloads.

    Links recommendations to their respective Namespace entities and updates
    the KubeRecommendations table with the latest calculated values.
    """

    def process(self, envelope: Any):
        """
        Main entry point for processing a KRR recommendation envelope.

        Validates the payload, resolves the namespace hierarchy, and 
        performs a bulk upsert of recommendation data.

        Args:
            envelope (Any): The ingestion message envelope.
        """
        payload_dict = envelope.payload
        try:
            batch = KRRBatchPayload.model_validate(payload_dict)
        except ValidationError as e:
            log.error(f"Invalid KRRBatchPayload: {e}")
            raise

        if not batch.recommendations:
            log.debug("Received empty KRR batch, skipping.")
            return

        # Use envelope timestamp or current time if missing
        scan_timestamp = getattr(envelope, 'timestamp', datetime.now(timezone.utc))

        values = []
        namespace_cache: Dict[str, int] = {}

        for item in batch.recommendations:
            # Create a standardized URN for the namespace (cluster:namespace)
            namespace_urn = f"{item.cluster_id}:namespace/{item.namespace}".lower()

            if namespace_urn not in namespace_cache:
                entity_id = self._resolve_hierarchy(item, namespace_urn)
                namespace_cache[namespace_urn] = entity_id
            
            entity_id = namespace_cache[namespace_urn]

            # Prepare recommendation record for bulk insertion
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
        log.info(f"Successfully processed {len(values)} KRR recommendations.")

    def _resolve_hierarchy(self, item: KRRRecommendationPayload, namespace_urn: str) -> int:
        """
        Ensures the hierarchy for a KRR recommendation (Provider - Cluster - Namespace).

        Args:
            item (KRRRecommendationPayload): The recommendation item.
            namespace_urn (str): The calculated URN for the namespace.

        Returns:
            int: The DB ID for the namespace entity.
        """
        provider = item.cloud_provider
        acc_id = item.account_id.lower()
        cluster_id = item.cluster_id.lower()
        cluster_name = item.cluster_name.lower()

        parent_id = 0
        
        # Resolve cloud provider account
        if provider == "azure":
            parent_id = self.resolve_azure_hierarchy(cluster_id)
        elif provider == "aws":
            parent_id = self.resolve_aws_hierarchy(acc_id)

        # Ensure the Kubernetes Cluster entity exists
        cluster_db_id = self.upsert_basic_entity(
            ext_id=cluster_id,
            provider=provider, 
            res_name=cluster_name, 
            res_type="kubernetes_cluster", 
            parent_id=parent_id
        )

        # Ensure the Kubernetes Namespace entity exists
        return self.upsert_basic_entity(
            ext_id=namespace_urn,
            provider=provider,
            res_name=item.namespace.lower(),
            res_type="kubernetes_namespace",
            parent_id=cluster_db_id
        )

    def _insert_recommendations(self, values: List[Tuple]):
        """
        Bulk-upserts recommendations into the KubeRecommendations table.

        Args:
            values (List[Tuple]): Prepared tuples for insertion.
        """
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