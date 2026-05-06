"""
Kubernetes Processor Module.

This module provides the KubeProcessor class, which handles the ingestion
of Kubernetes-related metrics (CPU, Memory) from Prometheus into the 
FinOps database.
"""

import json
import logging
from datetime import datetime
from typing import Any, List, Dict, Tuple, Optional
from psycopg2.extras import execute_values
from pydantic import ValidationError
from kube_collector.message import KubeMetricsPayload
from db_loader.base_processor import BaseProcessor, register_processor

log = logging.getLogger('kube_processor')


@register_processor("kube_collector")
class KubeProcessor(BaseProcessor):
    """
    Handles the ingestion of CPU and Memory metrics from Kubernetes clusters.

    Responsible for creating the hierarchy (Provider - Cluster - Namespace) 
    and bulk-inserting time-series metrics into the KubeMetrics table.
    """

    def process(self, envelope: Any):
        """
        Main entry point for processing a Kubernetes metrics envelope.

        Validates the payload, resolves the cluster/namespace hierarchy, 
        and performs a bulk upsert of metric datapoints.

        Args:
            envelope (Any): The ingestion message envelope.
        """
        payload_dict = envelope.payload
        try:
            payload = KubeMetricsPayload.model_validate(payload_dict)
        except ValidationError as e:
            log.error(f"Invalid KubeMetricsPayload: {e}")
            raise

        if not payload.datapoints:
            log.debug(f"No datapoints for namespace {payload.resource_name}, skipping.")
            return

        # Resolve entity hierarchy (Provider - Cluster - Namespace)
        entity_id = self._resolve_hierarchy(payload)

        tags_json = json.dumps(payload.tags)
        
        # Prepare values for bulk insertion
        values = [
            (
                entity_id,
                datetime.fromtimestamp(dp.timestamp),
                payload.metric_name.lower(),
                dp.value,
                tags_json  # Tags are stored as point-in-time snapshots
            )
            for dp in payload.datapoints
        ]

        self._insert_metrics(values)
        log.info(f"Saved {len(values)} records for namespace {payload.resource_name}.")

    def _resolve_hierarchy(self, payload: KubeMetricsPayload) -> int:
        """
        Creates/resolves the hierarchy of entities on top of cloud providers.

        Hierarchy: Cloud Account - K8s Cluster - Namespace.

        Args:
            payload (KubeMetricsPayload): The Kubernetes metric payload.

        Returns:
            int: The internal database ID of the namespace entity.
        """
        provider = payload.cloud_provider
        acc_id = payload.account_id.lower()
        resource_id = payload.resource_id.lower()
        
        # Logic to extract cluster ID from resource ID (format: cluster:namespace)
        cluster_id = ':'.join(resource_id.split(':')[:-1])
        cluster_name = payload.tags.get('cluster', 'unknown-cluster').lower()

        parent_id = 0
        
        # Resolve the cloud provider level
        if provider == "azure":
            parent_id = self.resolve_azure_hierarchy(resource_id)
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

        # Upsert Namespace Entity and merge tags
        tags_json = json.dumps(payload.tags)
        query = """
            INSERT INTO Entities (ExternalId, ProviderName, ResourceName, ResourceType, ParentId, Tags)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (ExternalId) DO UPDATE 
            SET 
                Tags = COALESCE(Entities.Tags, '{}'::jsonb) || COALESCE(EXCLUDED.Tags, '{}'::jsonb),
                ParentId = EXCLUDED.ParentId,
                UpdatedAt = NOW()
            RETURNING Id;
        """
        self.cursor.execute(query, (
            payload.resource_id.lower(), 
            provider.lower(), 
            payload.resource_name.lower(), 
            payload.resource_type.lower(), 
            cluster_db_id, 
            tags_json
        ))
        result = self.cursor.fetchone()
        if not result:
             # Fallback lookup if update didn't return (though it should with RETURNING)
            self.cursor.execute("SELECT Id FROM Entities WHERE ExternalId = %s;", (payload.resource_id.lower(),))
            result = self.cursor.fetchone()
            
        return result[0]

    def _insert_metrics(self, values: List[Tuple]):
        """
        Bulk-upserts metrics into the KubeMetrics table.

        Args:
            values (List[Tuple]): Prepared tuples for insertion.
        """
        query = """
            INSERT INTO KubeMetrics (EntityId, Timestamp, MetricName, Value, PointInTimeTags)
            VALUES %s
            ON CONFLICT (EntityId, Timestamp, MetricName) 
            DO UPDATE SET 
                Value = EXCLUDED.Value,
                PointInTimeTags = EXCLUDED.PointInTimeTags;
        """
        execute_values(self.cursor, query, values)