import json
import hashlib
from psycopg2.extras import execute_values

class MetricsProcessor:
    """
    Class to process measured metrics by Custodian and insert into DB.
    """
    def __init__(self, db_conn):
        self.db = db_conn
        self.cursor = self.db.cursor()

    def process(self, envelope):
        payload_data = envelope.payload
        
        provider = payload_data['provider']
        resource_id = payload_data['resource_id']
        
        # Compute hash for resource metadata, replace if differs.
        metadata_str = json.dumps({"tags": payload_data.get('tags'),
                                    "extras": payload_data.get('extras')},
                                    sort_keys=True)
        current_hash = hashlib.md5(metadata_str.encode('utf-8')).hexdigest()

        # Get entity ID, and create/update values if needed. 
        numeric_entity_id = self._resolve_entity_and_parent(
            provider, resource_id, payload_data['billing_account_id'], payload_data, current_hash
        )

        # Bulk insert into Metrics
        datapoints = payload_data.get('datapoints', [])
        if datapoints:
            self._insert_metrics(numeric_entity_id, payload_data['metric_name'], datapoints, payload_data['metric_period'])


    def _resolve_entity_and_parent(self, provider, resource_id, account_id, payload, current_hash):
        """Finds or creates Entity, creates hierarchical structure from metadata"""
        
        parent_id = 0
        
        if provider == "azure":
            parts = resource_id.split("/")
            #TODO make more robust
            if len(parts) > 4:
                sub_id = parts[2]
                rg_name = parts[4]
                # Create subscription and resource group entity
                parent_id = self._upsert_entity(f"/subscriptions/{sub_id}",sub_id, "subscription", "0", 0, provider)
                parent_id = self._upsert_entity(f"/subscriptions/{sub_id}/resourcegroups/{rg_name}",rg_name, "resource_group", "0", parent_id, provider)
                
        elif provider == "aws":
            # AWS hierarchy is account-id only
            parent_id = self._upsert_entity(account_id,account_id, "aws_account", "0", 0, provider)

        # Create/update current resource
        return self._upsert_entity(
            resource_id=resource_id,
            res_name=payload['resource_name'], 
            res_type=payload['resource_type'], 
            meta_hash=current_hash, 
            parent_id=parent_id,
            provider=provider,
            tags=json.dumps(payload.get('tags', {})),
            extras=json.dumps(payload.get('extras', {}))
        )

    def _upsert_entity(self, resource_id,res_name, res_type, meta_hash, parent_id, provider, tags="{}", extras="{}"):
        """
            Uses SQL UPSERT to update tags and extras if the hash isn't matching.
            Returns entity ID.
        """
        query = """
            INSERT INTO Entities (ExternalId, ResourceName, ResourceType, ParentId, MetaHash, Tags, Extras, ProviderName)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ExternalId) DO UPDATE 
            SET MetaHash = EXCLUDED.MetaHash,
                Tags = EXCLUDED.Tags,
                Extras = EXCLUDED.Extras
            WHERE entities.MetaHash != EXCLUDED.MetaHash
            RETURNING Id;
        """
        if not res_name or res_name == "None":
            res_name = resource_id
        self.cursor.execute(query, (resource_id.lower(), res_name.lower(),res_type.lower(), parent_id, meta_hash, tags, extras, provider))
        result = self.cursor.fetchone()
        
        if result:
            return result[0]
        else:
            # Hash hasn't changed, extra select query is needed.
            self.cursor.execute("SELECT Id FROM Entities WHERE ExternalId = %s;", (resource_id.lower(),))
            return self.cursor.fetchone()[0]

    def _insert_metrics(self, entity_id, metric_name, datapoints, interval):
        """Bulk-upsert of metrics into Metrics table"""

        query = "INSERT INTO metrics (EntityId, MetricType, Timestamp, Value, IntervalMinutes) VALUES %s" \
        "ON CONFLICT (EntityId, MetricType, Timestamp) " \
        "DO NOTHING;"
        # Unify the metric name accross different resource_types. 
        metric_name = "_".join(metric_name.split("_")[1:])
        # Parse the datapoint entries into tuples
        values = [(entity_id, metric_name.lower(), dp['timestamp'], dp['value'], interval) for dp in datapoints]
        
        execute_values(self.cursor, query, values)