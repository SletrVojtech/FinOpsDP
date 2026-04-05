import logging
from psycopg2.extras import execute_values
from db_loader.base_processor import BaseProcessor, register_processor

log = logging.getLogger('catalog_processor')

@register_processor("catalog_downloader")
class CatalogProcessor(BaseProcessor):
    """
    Class to process cloud hardware specs and pricing catalogs and insert them into DB.
    """

    def process(self, envelope):
        payload_data = envelope.payload

        hardware_records = payload_data.get('hardware_records', [])
        pricing_records = payload_data.get('pricing_records', [])

        # Parse the hardware records
        if hardware_records:
            self._upsert_hardware(hardware_records)
            log.info(f"Successfully processed {len(hardware_records)} hardware records.")

        # Parse the pricing
        if pricing_records:
            self._upsert_pricing(pricing_records)
            log.info(f"Successfully processed {len(pricing_records)} pricing records.")


    def _upsert_hardware(self, hardware_records):
        """Bulk-upsert of hardware specifications."""
        query = """
            INSERT INTO hardwarecatalog AS target (
                cloud, instance_type, instance_family, vcpu, memory_gb,
                baseline_iops, baseline_throughput_mbps, network_performance,
                architecture, is_gpu, is_confidential, has_local_storage, supports_premium_storage
            ) VALUES %s
            ON CONFLICT (cloud, instance_type) DO UPDATE SET
                instance_family = EXCLUDED.instance_family,
                vcpu = EXCLUDED.vcpu,
                memory_gb = EXCLUDED.memory_gb,
                baseline_iops = EXCLUDED.baseline_iops,
                baseline_throughput_mbps = EXCLUDED.baseline_throughput_mbps,
                network_performance = EXCLUDED.network_performance,
                architecture = EXCLUDED.architecture,
                is_gpu = EXCLUDED.is_gpu,
                is_confidential = EXCLUDED.is_confidential,
                has_local_storage = EXCLUDED.has_local_storage,
                supports_premium_storage = EXCLUDED.supports_premium_storage,
                updated_at = CURRENT_TIMESTAMP
            WHERE target.vcpu != EXCLUDED.vcpu
               OR target.memory_gb != EXCLUDED.memory_gb
               OR target.baseline_iops IS DISTINCT FROM EXCLUDED.baseline_iops
               OR target.architecture IS DISTINCT FROM EXCLUDED.architecture
               OR target.is_gpu != EXCLUDED.is_gpu
               OR target.is_confidential != EXCLUDED.is_confidential
               OR target.has_local_storage != EXCLUDED.has_local_storage
               OR target.supports_premium_storage != EXCLUDED.supports_premium_storage;
        """

        values = [
            (
                r['cloud'],
                r['instance_type'].lower(),
                r.get('instance_family', '').lower(),
                r['vcpu'],
                r['memory_gb'],
                r.get('baseline_iops'),
                r.get('baseline_throughput_mbps'),
                r.get('network_performance'),
                r.get('architecture', 'x86_64'),
                bool(r.get('is_gpu', False)),
                bool(r.get('is_confidential', False)),
                bool(r.get('has_local_storage', False)),
                bool(r.get('supports_premium_storage', False)),
            )
            for r in hardware_records
        ]

        execute_values(self.cursor, query, values)


    def _upsert_pricing(self, pricing_records):
        """Bulk-upsert of pricing records."""
        query = """
            INSERT INTO pricingcatalog AS target(
                cloud, instance_type, region, os, hourly_price_usd
            ) VALUES %s
            ON CONFLICT (cloud, instance_type, region, os) DO UPDATE SET
                hourly_price_usd = EXCLUDED.hourly_price_usd,
                updated_at = CURRENT_TIMESTAMP
            WHERE target.hourly_price_usd != EXCLUDED.hourly_price_usd;
        """

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