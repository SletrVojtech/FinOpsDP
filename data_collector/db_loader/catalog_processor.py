"""
Catalog Processor Module.

This module provides the CatalogProcessor class, which handles the ingestion
of cloud hardware specifications and pricing information into the FinOps database.
"""

import logging
from typing import Any, List, Dict, Tuple, Optional
from psycopg2.extras import execute_values
from db_loader.base_processor import BaseProcessor, register_processor

log = logging.getLogger('catalog_processor')


@register_processor("catalog_downloader")
class CatalogProcessor(BaseProcessor):
    """
    Handles the ingestion of cloud hardware and pricing catalogs.

    Updates the HardwareCatalog and PricingCatalog tables with normalized 
    data from various cloud providers.
    """

    def process(self, envelope: Any):
        """
        Main entry point for processing a catalog envelope.

        Dispatches hardware records and pricing records to their respective
        upsert methods.

        Args:
            envelope (Any): The ingestion message envelope.
        """
        payload_data = envelope.payload

        hardware_records = payload_data.get('hardware_records', [])
        pricing_records = payload_data.get('pricing_records', [])

        # Process hardware specifications
        if hardware_records:
            self._upsert_hardware(hardware_records)
            log.info(f"Successfully processed {len(hardware_records)} hardware records.")

        # Process pricing information
        if pricing_records:
            self._upsert_pricing(pricing_records)
            log.info(f"Successfully processed {len(pricing_records)} pricing records.")

    def _upsert_hardware(self, hardware_records: List[Dict[str, Any]]):
        """
        Performs a bulk upsert of hardware specifications.

        Args:
            hardware_records (List[Dict[str, Any]]): List of hardware record dictionaries.
        """
        query = """
            INSERT INTO HardwareCatalog AS target (
                Cloud, InstanceType, InstanceFamily, VCPU, MemoryGB,
                BaselineIOPS, BaselineThroughputMBps, NetworkPerformance,
                Architecture, IsGPU, IsConfidential, HasLocalStorage, SupportsPremiumStorage
            ) VALUES %s
            ON CONFLICT (Cloud, InstanceType) DO UPDATE SET
                InstanceFamily = EXCLUDED.InstanceFamily,
                VCPU = EXCLUDED.VCPU,
                MemoryGB = EXCLUDED.MemoryGB,
                BaselineIOPS = EXCLUDED.BaselineIOPS,
                BaselineThroughputMBps = EXCLUDED.BaselineThroughputMBps,
                NetworkPerformance = EXCLUDED.NetworkPerformance,
                Architecture = EXCLUDED.Architecture,
                IsGPU = EXCLUDED.IsGPU,
                IsConfidential = EXCLUDED.IsConfidential,
                HasLocalStorage = EXCLUDED.HasLocalStorage,
                SupportsPremiumStorage = EXCLUDED.SupportsPremiumStorage,
                UpdatedAt = CURRENT_TIMESTAMP
            WHERE target.VCPU != EXCLUDED.VCPU
               OR target.MemoryGB != EXCLUDED.MemoryGB
               OR target.BaselineIOPS IS DISTINCT FROM EXCLUDED.BaselineIOPS
               OR target.Architecture IS DISTINCT FROM EXCLUDED.Architecture
               OR target.IsGPU != EXCLUDED.IsGPU
               OR target.IsConfidential != EXCLUDED.IsConfidential
               OR target.HasLocalStorage != EXCLUDED.HasLocalStorage
               OR target.SupportsPremiumStorage != EXCLUDED.SupportsPremiumStorage;
        """

        # Prepare values for bulk insertion
        values = [
            (
                r['cloud'].lower(),
                r['instance_type'].lower(),
                r.get('instance_family', '').lower(),
                r['vcpu'],
                r['memory_gb'],
                r.get('baseline_iops'),
                r.get('baseline_throughput_mbps'),
                r.get('network_performance'),
                r.get('architecture', 'x86_64').lower(),
                bool(r.get('is_gpu', False)),
                bool(r.get('is_confidential', False)),
                bool(r.get('has_local_storage', False)),
                bool(r.get('supports_premium_storage', False)),
            )
            for r in hardware_records
        ]

        execute_values(self.cursor, query, values)

    def _upsert_pricing(self, pricing_records: List[Dict[str, Any]]):
        """
        Performs a bulk upsert of pricing records.

        Args:
            pricing_records (List[Dict[str, Any]]): List of pricing record dictionaries.
        """
        query = """
            INSERT INTO PricingCatalog AS target(
                Cloud, InstanceType, Region, Os, HourlyPriceUsd
            ) VALUES %s
            ON CONFLICT (Cloud, InstanceType, Region, Os) DO UPDATE SET
                HourlyPriceUsd = EXCLUDED.HourlyPriceUsd,
                UpdatedAt = CURRENT_TIMESTAMP
            WHERE target.HourlyPriceUsd != EXCLUDED.HourlyPriceUsd;
        """

        # Prepare values for bulk insertion
        values = [
            (
                r['cloud'].lower(),
                r['instance_type'].lower(),
                r['region'].lower(),
                r['os'].lower(),
                r['hourly_price_usd']
            )
            for r in pricing_records
        ]

        execute_values(self.cursor, query, values, page_size=5000)