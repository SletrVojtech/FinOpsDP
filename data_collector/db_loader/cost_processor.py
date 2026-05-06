"""
Cost Processor Module.

This module provides the CostsProcessor class, which handles the ingestion
of cost data into the database.
"""

import json
import logging
from typing import Any, List, Dict, Tuple, Optional
from psycopg2.extras import execute_values
from pydantic import ValidationError
from cost_collector.message import CostBatchPayload, CostPayload
from db_loader.base_processor import BaseProcessor, register_processor

log = logging.getLogger('cost_processor')


@register_processor("cost_export")
class CostsProcessor(BaseProcessor):
    """
    Handles the ingestion of cost records collected from cloud providers.

    Responsible for resolving cloud resource hierarchies (Billing Accounts, 
    Subscriptions/AWS Accounts) and bulk-upserting cost records into the 
    Costs hypertable.
    """

    def process(self, envelope: Any):
        """
        Main entry point for processing a cost batch envelope.

        Validates the payload, resolves entity IDs in bulk, and performs 
        a bulk upsert of cost data.

        Args:
            envelope (Any): The ingestion message envelope.
        """
        body = envelope.payload
        try:
            batch = CostBatchPayload.model_validate(body)
        except ValidationError as e:
            log.error(f"Invalid cost payload: {e}")
            raise

        if not batch.records:
            log.debug("Received empty cost batch, skipping.")
            return

        # Resolve all resource Entity IDs in bulk
        entity_map = self._resolve_entities_bulk(batch.records)

        # Prepare records for bulk insert
        cost_values = []
        for record in batch.records:
            entity_id = entity_map.get(record.resource_id.lower())
            if not entity_id:
                log.warning(f"Could not resolve entity for resource: {record.resource_id}")
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
            log.info(f"Successfully processed {len(cost_values)} cost records.")

    def _get_or_create_parent(self, record: CostPayload, cache: Dict[str, int]) -> int | None:
        """
        Ensures the parent hierarchy (Billing Account -> Account/Sub) exists.

        Args:
            record (CostPayload): The cost record being processed.
            cache (Dict[str, int]): Local entity ID cache.

        Returns:
            int: The DB ID of the immediate parent entity.
        """
        provider = record.provider
        res_id = record.resource_id
        billing_id = record.billing_id
        billing_name = record.billing_name
        account_name = record.account_name
        
        # Ensure Billing Account exists
        if billing_id not in cache:
            cache[billing_id] = self.upsert_basic_entity(
                billing_id, provider, billing_name, "billing_account", 0, cache
            )

        # Resolve provider-specific hierarchy
        if provider == "aws":
            return self.resolve_aws_hierarchy(
                record.account_id, 
                account_name=account_name, 
                parent_id=cache[billing_id], 
                cache=cache
            )
        elif provider == "azure":
            return self.resolve_azure_hierarchy(
                resource_id=res_id, 
                parent_id=cache[billing_id], 
                cache=cache, 
                fallback_sub_id=record.account_id, 
                fallback_sub_name=account_name
            )

        return None

    def _resolve_entities_bulk(self, records: List[CostPayload]) -> Dict[str, int]:
        """
        Resolves or creates all entities in the batch in bulk.

        Args:
            records (List[CostPayload]): The list of cost records.

        Returns:
            Dict[str, int]: A mapping of ExternalId to DB ID.
        """
        # Deduplicate resources to avoid redundant upserts
        unique_entities = {record.resource_id.lower(): record for record in records}

        parent_cache: Dict[str, int] = {}
        entity_values = []
        
        # SQL for bulk entity upsert. 
        # Merges tags using JSONB concatenation and updates the region.
        insert_query = """
            INSERT INTO Entities (ExternalId, ProviderName, ResourceName, ResourceType, ParentId, Tags, RegionId)
            VALUES %s
            ON CONFLICT (ExternalId) DO UPDATE 
            SET 
                Tags = COALESCE(Entities.Tags, '{}'::jsonb) || COALESCE(EXCLUDED.Tags, '{}'::jsonb),
                RegionId = EXCLUDED.RegionId, 
                UpdatedAt = NOW()
            RETURNING Id, ExternalId;
        """

        for ext_id, rec in unique_entities.items():
            parent_id = self._get_or_create_parent(rec, parent_cache)
            
            res_name = rec.resource_id if (not rec.resource_name or rec.resource_name == "None") else rec.resource_name
            
            entity_values.append((
                ext_id,
                rec.provider.lower(),
                res_name.lower(),
                rec.resource_type.lower(),
                parent_id,
                json.dumps(rec.tags) if rec.tags else "{}",
                rec.region_id
            ))
        
        # Execute bulk insert and capture results for mapping
        results = execute_values(self.cursor, insert_query, entity_values, fetch=True)
        
        return {row[1]: row[0] for row in results}

    def _insert_costs_bulk(self, cost_values: List[Tuple]):
        """
        Performs a bulk upsert of cost data into the Costs table.

        Args:
            cost_values (List[Tuple]): Prepared tuples for insertion.
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