"""
Cost Message Adapter Module.

This module provides the FocusCostAdapter class which maps parsed row
dictionaries into Pydantic CostPayload objects.
"""

import json
from cost_collector.message import CostPayload


class FocusCostAdapter:
    """
    FOCUS 1.2 adapter class.
    
    Transforms raw dictionary rows from DuckDB queries into validated
    CostPayload objects based on the FOCUS specification.
    """
    
    def __init__(self, row: dict):
        """
        Initialize the adapter with a row of cost data.

        Args:
            row (dict): A dictionary representing a single cost record.
        """
        self.row = row

    def get_provider(self) -> str:
        """
        Extract and normalize the cloud provider name.

        Returns:
            str: The normalized provider name ('aws', 'azure', or 'unknown').
        """
        provider = str(self.row.get('ProviderName', '')).lower()
        if 'aws' in provider or 'amazon' in provider:
            return 'aws'
        elif 'microsoft' in provider or 'azure' in provider:
            return 'azure'
        return 'unknown'

    def get_account_id(self) -> str:
        """
        Extract the normalized account ID.

        Returns:
            str: The normalized account ID.
        """
        acc_id = str(self.row.get('SubAccountId', ''))
        if "subscriptions/" in acc_id.lower():
            return acc_id.split("/")[-1]
        return acc_id

    def get_resource_id(self) -> str:
        """
        Extract a valid resource ID, falling back to service name if necessary.

        Returns:
            str: The resource ID or a generic fallback.
        """
        res_id = self.row.get('resource_id')
        if not res_id:
            service = self.row.get('ServiceName', 'general')
            return str(service)
        return str(res_id)

    def get_tags(self) -> dict:
        """
        Extract and parse the resource tags.

        Returns:
            dict: A dictionary of tags.
        """
        tags_raw = self.row.get('Tags')
        if not tags_raw:
            return {}
        if isinstance(tags_raw, dict):
            return tags_raw
        if isinstance(tags_raw, str):
            try: return json.loads(tags_raw)
            except: return {}
        return {}


    def to_payload(self) -> CostPayload:
        """
        Convert the raw row data into a CostPayload object.

        Returns:
            CostPayload: The validated Pydantic model.
        """
        return CostPayload(
            provider=self.get_provider(),
            billing_id=str(self.row.get('BillingAccountId', 'Unknown')),
            billing_name=str(self.row.get('BillingAccountName', 'Unknown')),
            account_id=self.get_account_id(),
            account_name=str(self.row.get('SubAccountName', 'Unknown')),
            region_id=str(self.row.get('RegionId', 'Unknown')),
            
            resource_id=self.get_resource_id(),
            resource_name=str(self.row.get('ResourceName', self.get_resource_id())),
            resource_type=str(self.row.get('ResourceType', 'Unknown')),
            tags=self.get_tags(),
            service_name=str(self.row.get('ServiceName', 'Unknown')),
            service_category=str(self.row.get('ServiceCategory', 'Unknown')),
            sku_price_id=str(self.row.get('SkuPriceId', 'Unknown')),
            
            charge_period_start=self.row.get('charge_period_start'),
            charge_period_end=self.row.get('charge_period_end'),
            
            billed_cost=float(self.row.get('billed_cost', 0.0) or 0.0),
            billing_currency=str(self.row.get('BillingCurrency', 'EUR')),
            
        )