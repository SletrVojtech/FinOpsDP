import json
import logging
from psycopg2.extras import execute_values
from pydantic import ValidationError
from kube_collector.message import KubeMetricsPayload
from datetime import datetime
from db_loader.base_processor import BaseProcessor, register_processor


log = logging.getLogger('kube_processor')

@register_processor("kube_collector")
class KubeProcessor(BaseProcessor):
    """
    Parse CPU and Memory metrics from Prometheus into DB.
    Creates hierarchy of entities on top of cloud providers.
    """

    def process(self, envelope):
        payload_dict = envelope.payload
        try:
            payload = KubeMetricsPayload.model_validate(payload_dict)
        except ValidationError as e:
            log.error(f"Invalid KubeMetricsPayload: {e}")
            raise

        if not payload.datapoints:
            return

        # Solve entity hierarchy
        entity_id = self._resolve_hierarchy(payload)

        tags_json = json.dumps(payload.tags)
        
        values = [
            (
                entity_id,
                datetime.fromtimestamp(dp.timestamp),
                payload.metric_name.lower(),
                dp.value,
                tags_json # Tags are stored in-time
            )
            for dp in payload.datapoints
        ]

        self._insert_metrics(values)
        log.debug(f"Saved {len(values)} records for namespace {payload.resource_name}.")

    def _resolve_hierarchy(self, payload) -> int:
        """
            Creates hierarchy of entities on top of cloud providers.
            Returns entity ID.
        """
        provider = payload.cloud_provider
        acc_id = payload.account_id.lower()
        resource_id = payload.resource_id.lower()
        cluster_id = ':'.join(resource_id.split(':')[:-1])
        cluster_name = payload.tags.get('cluster', 'unknown-cluster').lower()

        parent_id = 0
        
        if provider == "azure":
            parent_id = self.resolve_azure_hierarchy(resource_id)
                
        elif provider == "aws":
            parent_id = self.resolve_aws_hierarchy(acc_id)


        # UPSERT  k8s cluster
        cluster_db_id = self.upsert_basic_entity(
            ext_id=cluster_id,
            provider=provider, 
            res_name=cluster_name, 
            res_type="kubernetes_cluster", 
            parent_id=parent_id
        )

        # Namespace Entity, update tags.
        tags_json = json.dumps(payload.tags)
        query = """
            INSERT INTO Entities (ExternalId, ProviderName, ResourceName, ResourceType, ParentId, Tags)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (ExternalId) DO UPDATE 
            SET 
                Tags = COALESCE(Entities.Tags, '{}'::jsonb) || COALESCE(EXCLUDED.Tags, '{}'::jsonb),
                ParentId = EXCLUDED.ParentId
            RETURNING Id;
        """
        self.cursor.execute(query, (
            payload.resource_id, 
            provider, 
            payload.resource_name.lower(), 
            payload.resource_type.lower(), 
            cluster_db_id, 
            tags_json
        ))
        return self.cursor.fetchone()[0]

    def _insert_metrics(self, values: list):
        """Bulk UPSERT of metrics into  KubeMetrics table"""
        query = """
            INSERT INTO KubeMetrics (EntityId, Timestamp, MetricName, Value, PointInTimeTags)
            VALUES %s
            ON CONFLICT (EntityId, Timestamp, MetricName) 
            DO UPDATE SET 
                Value = EXCLUDED.Value,
                PointInTimeTags = EXCLUDED.PointInTimeTags;
        """
        execute_values(self.cursor, query, values)