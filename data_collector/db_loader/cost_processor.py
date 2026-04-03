import json
import logging
from psycopg2.extras import execute_values
from pydantic import ValidationError
from cost_collector.message import CostBatchPayload
from db_loader.base_processor import BaseProcessor, register_processor


log = logging.getLogger('cost_processor')

@register_processor("cost_export")
class CostsProcessor(BaseProcessor):

    def process(self, envelope):
        body = envelope.payload
        try:
            batch = CostBatchPayload.model_validate(body)
        except ValidationError as e:
            log.error(f"Invalid payload: {e}")
            raise

        if not batch.records:
            return

        # Find all EntityIDs
        entity_map = self._resolve_entities_bulk(batch.records)

        # Prepare bulk insert
        cost_values = []
        for record in batch.records:
            entity_id = entity_map.get(record.resource_id.lower())
            if not entity_id:
                log.warning(f"Couldn't find entity for resource: {record.resource_id}")
                continue

            cost_values.append((
                entity_id,
                record.billed_cost,
                record.billing_currency,
                record.charge_period_start,
                record.charge_period_end,
                record.service_category.lower(),
                record.service_name.lower(),
                record.sku_price_id.lower(),
            ))

        if cost_values:
            self._insert_costs_bulk(cost_values)
            log.info(f"Successfully inserted {len(cost_values)} records.")


    def _get_or_create_parent(self,record, cache):
        """
        Generates a hierarchy of resource entities.
        """
        provider = record.provider
        res_id = record.resource_id
        billing_id = record.billing_id
        billing_name = record.billing_name
        account_name = record.account_name
        
        if billing_id not in cache:
            cache[billing_id] = self.upsert_basic_entity(billing_id, provider, billing_name, "billing_account", 0, cache)

        if provider == "aws":
            return self.resolve_aws_hierarchy(record.account_id, account_name=account_name, parent_id=cache[billing_id], cache=cache)

        elif provider == "azure":
            return self.resolve_azure_hierarchy(
                resource_id=res_id, 
                parent_id=cache[billing_id], 
                cache=cache, 
                fallback_sub_id=record.account_id, 
                fallback_sub_name=account_name
            )

        return None

    def _resolve_entities_bulk(self, records) -> dict:
        """
        Finds/Creates/Updates all entities
        """

        unique_entities = { record.resource_id: record for record in records }

        parent_cache = {}
        entity_values = []
        
        # JSONB concatenation based on https://www.postgresql.org/docs/9.5/functions-json.html
        # Coalesce to prevent NULL values
        # Some resources aren't updated by MetricsProcessor, but CostExports don't necessarily see all existing tags.
        insert_query = """
            INSERT INTO Entities (ExternalId, ProviderName, ResourceName, ResourceType,ParentId, Tags, RegionId)
            VALUES %s
            ON CONFLICT (ExternalId) DO UPDATE 
            SET 
                Tags = COALESCE(Entities.Tags, '{}'::jsonb) || COALESCE(EXCLUDED.Tags, '{}'::jsonb),
                RegionId = EXCLUDED.RegionId
            RETURNING Id, ExternalId
        """

        for rec in unique_entities.values():
            parent_id = self._get_or_create_parent(rec, parent_cache)
            if not rec.resource_name or rec.resource_name == "None":
                rec.resource_name = rec.resource_id
            entity_values.append((
                rec.resource_id.lower(),
                rec.provider.lower(),
                rec.resource_name.lower(),
                rec.resource_type.lower(),
                parent_id,
                json.dumps(rec.tags) if rec.tags else "{}",
                rec.region_id
            ))
        
        
        results = execute_values(self.cursor, insert_query, entity_values, fetch=True)
        
        # Return a dictionary for external ID and EntityID
        return {row[1]: row[0] for row in results}


    def _insert_costs_bulk(self, cost_values: list):
        """
        """
        query = """
            INSERT INTO Costs (
                EntityId, BilledCost, BillingCurrency, ChargePeriodStart, ChargePeriodEnd, 
                ServiceCategory, ServiceName, SkuPriceId
            ) VALUES %s
            ON CONFLICT (EntityId, ChargePeriodStart, ServiceName, SkuPriceId) 
            DO UPDATE SET 
                BilledCost = EXCLUDED.BilledCost,
                ChargePeriodEnd = EXCLUDED.ChargePeriodEnd
        """
        execute_values(self.cursor, query, cost_values)