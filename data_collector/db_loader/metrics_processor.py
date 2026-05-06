"""
Metrics Processor Module.

This module provides the MetricsProcessor class, which handles the ingestion
of cloud-native metrics (from Cloud Custodian) into the timeseries database.
"""

import json
import hashlib
import logging
from typing import Any, List, Dict, Tuple, Optional
from psycopg2.extras import execute_values
from db_loader.base_processor import BaseProcessor, register_processor

log = logging.getLogger('metrics_processor')


@register_processor("custodian")
class MetricsProcessor(BaseProcessor):
    """
    Handles the ingestion of resource metrics collected by Cloud Custodian.

    Responsible for resolving cloud-native IDs into internal entity IDs, 
    maintaining metadata consistency via hashing, and bulk-inserting 
    time-series data.
    """

    def process(self, envelope: Any):
        """
        Main entry point for processing a metrics envelope.

        Extracts resource metadata, calculates a hash, resolves the entity, 
        and triggers bulk insertion of datapoints.

        Args:
            envelope (Any): The ingestion message envelope.
        """
        payload_data = envelope.payload
        
        provider = payload_data['provider']
        resource_id = payload_data['resource_id']
        
        # Compute hash for resource metadata. This allows us to skip unnecessary
        # DB updates if tags and extras haven't changed since the last collection.
        metadata_str = json.dumps({"tags": payload_data.get('tags'),
                                    "extras": payload_data.get('extras')},
                                    sort_keys=True)
        current_hash = hashlib.md5(metadata_str.encode('utf-8')).hexdigest()

        # Resolve entity ID, and create/update values if metadata hash has changed.
        numeric_entity_id = self._resolve_entity_and_parent(
            provider, resource_id, payload_data['billing_account_id'], payload_data, current_hash
        )

        # Bulk insert metric datapoints
        datapoints = payload_data.get('datapoints', [])
        if datapoints:
            self._insert_metrics(
                numeric_entity_id, 
                payload_data['metric_name'], 
                datapoints, 
                payload_data['metric_period']
            )

    def _resolve_entity_and_parent(self, provider: str, resource_id: str, 
                                     account_id: str, payload: Dict[str, Any], 
                                     current_hash: str) -> int:
        """
        Resolves the entity ID and ensures the parent hierarchy is established.

        Args:
            provider (str): Cloud provider (aws/azure).
            resource_id (str): External resource ID.
            account_id (str): Billing account identifier.
            payload (Dict[str, Any]): Full payload for metadata extraction.
            current_hash (str): The calculated metadata hash.

        Returns:
            int: The internal database ID of the entity.
        """
        parent_id = 0
        
        if provider == "azure":
            parent_id = self.resolve_azure_hierarchy(resource_id)
        elif provider == "aws":
            parent_id = self.resolve_aws_hierarchy(account_id)

        # Create or update current resource entity
        return self._upsert_entity(
            resource_id=resource_id,
            res_name=payload.get('resource_name'), 
            res_type=payload.get('resource_type', 'resource'), 
            meta_hash=current_hash, 
            parent_id=parent_id,
            provider=provider,
            tags=json.dumps(payload.get('tags', {})),
            extras=json.dumps(payload.get('extras', {}))
        )

    def _upsert_entity(self, resource_id: str, res_name: Optional[str], 
                       res_type: str, meta_hash: str, parent_id: int, 
                       provider: str, tags: str = "{}", extras: str = "{}") -> int:
        """
        Performs a conditional UPSERT on the Entities table.

        Updates tags and extras only if the meta_hash has changed.

        Args:
            resource_id (str): External identifier.
            res_name (Optional[str]): Human-readable name.
            res_type (str): Resource type string.
            meta_hash (str): Hash of current metadata.
            parent_id (int): DB ID of the parent entity.
            provider (str): Provider name.
            tags (str): JSON string of tags.
            extras (str): JSON string of extra metadata.

        Returns:
            int: Internal entity ID.
        """
        query = """
            INSERT INTO Entities (ExternalId, ResourceName, ResourceType, ParentId, MetaHash, Tags, Extras, ProviderName)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ExternalId) DO UPDATE 
            SET MetaHash = EXCLUDED.MetaHash,
                Tags = EXCLUDED.Tags,
                Extras = EXCLUDED.Extras,
                UpdatedAt = NOW()
            WHERE entities.MetaHash != EXCLUDED.MetaHash
            RETURNING Id;
        """
        
        # Fallback for resource name
        final_name = resource_id if (not res_name or str(res_name).lower() == "none") else res_name
        
        self.cursor.execute(query, (
            resource_id.lower(), 
            str(final_name).lower(), 
            res_type.lower(), 
            parent_id, 
            meta_hash, 
            tags, 
            extras, 
            provider.lower()
        ))
        result = self.cursor.fetchone()
        
        if result:
            return result[0]
        else:
            # Hash hasn't changed, retrieve existing ID
            self.cursor.execute("SELECT Id FROM Entities WHERE ExternalId = %s;", (resource_id.lower(),))
            res = self.cursor.fetchone()
            if not res:
                raise RuntimeError(f"Entity {resource_id} not found.")
            return res[0]

    def _insert_metrics(self, entity_id: int, metric_name: str, 
                        datapoints: List[Dict[str, Any]], interval: int):
        """
        Bulk-inserts metrics into the Metrics table.

        Args:
            entity_id (int): The target entity DB ID.
            metric_name (str): Original metric name.
            datapoints (List[Dict[str, Any]]): List of (timestamp, value) pairs.
            interval (int): Metric period in minutes.
        """
        query = (
            "INSERT INTO Metrics (EntityId, MetricType, Timestamp, Value, IntervalMinutes) VALUES %s "
            "ON CONFLICT (EntityId, MetricType, Timestamp) DO NOTHING;"
        )
        
        # Unify metric name by removing provider prefix (e.g., aws_ec2_cpu_avg -> ec2_cpu_avg)
        # Note: Logic assumes provider_resource_metric format.
        name_parts = metric_name.split("_")
        if len(name_parts) > 1:
            unified_metric_name = "_".join(name_parts[1:])
        else:
            unified_metric_name = metric_name

        # Prepare values for bulk insertion
        values = [
            (entity_id, unified_metric_name.lower(), dp['timestamp'], dp['value'], interval) 
            for dp in datapoints
        ]
        
        execute_values(self.cursor, query, values)