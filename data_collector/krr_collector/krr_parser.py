"""
KRR File Parser Module.

This module provides the KRRFileParser class for transforming Robusta KRR JSON output
into RabbitMQ-compatible ingestion messages.
"""

import logging
from typing import List, Any, Dict

from rabbitmq.message import IngestionMessage
from krr_collector.message import KRRRecommendationPayload, KRRBatchPayload
from rabbitmq.connector import RabbitMQClient


log = logging.getLogger("krr_file_parser")

class KRRFileParser:
    """
    Parses Robusta KRR JSON output and prepares it for ingestion.
    """
    def __init__(self, krr_data: Dict[str, Any], cluster_info: Dict[str, Any]):
        """
        Initialize the parser with KRR data and cluster context.

        Args:
            krr_data (Dict[str, Any]): The raw JSON output from the KRR tool.
            cluster_info (Dict[str, Any]): Metadata about the cluster being scanned.
        """
        self.krr_data = krr_data
        self.cluster_info = cluster_info

    def parse_to_rabbitmq(self) -> List[IngestionMessage]:
        """
        Transforms the internal KRR data into a list of RabbitMQ ingestion messages.

        Returns:
            List[IngestionMessage]: A list containing a single batch message with all recommendations.
        """

        provider = self.cluster_info.get('provider', 'unknown')
        account_id = self.cluster_info.get('account_id', 'unknown')
        cluster_id = self.cluster_info.get('cluster_resource_id', 'unknown')
        cluster_name_conf = self.cluster_info.get('cluster_name', 'unknown')

        payload_batch = []
        if not self.krr_data:
            log.warning("JSON with no recommendations found.")
            return []

        # iterate the returned objects
        for scan in self.krr_data.get('scans', []):
            obj = scan.get('object', {})
            
            ns = obj.get('namespace')
            obj_name = obj.get('name')
            obj_type = obj.get('kind')
            container = obj.get('container')

            if not ns or not obj_name:
                continue

            # Create unique ID, hierarchic to KubePrometheusCollector
            resource_urn = f"{cluster_id}:namespace/{ns}:{obj_type}/{obj_name}:container/{container}"

            # Get current values
            current_allocations = obj.get('allocations', {}).get('requests', {})
            cur_cpu = current_allocations.get('cpu')
            cur_mem = current_allocations.get('memory')

            # Recommendations
            recs = scan.get('recommended', {}).get('requests', {})
            # Parse from {"value": 0.01, "severity": "WARNING"}
            rec_cpu = recs.get('cpu', {}).get('value') if isinstance(recs.get('cpu'), dict) else None
            rec_mem = recs.get('memory', {}).get('value') if isinstance(recs.get('memory'), dict) else None
            item = KRRRecommendationPayload(
                cloud_provider=provider,
                account_id=account_id,
                cluster_name=cluster_name_conf,
                cluster_id=cluster_id,
                resource_id=resource_urn,
                namespace=ns,
                workload_type=obj_type,
                workload_name=obj_name,
                container_name=container,
                

                current_cpu_request=str(cur_cpu) if cur_cpu is not None else None,
                recommended_cpu_request=str(rec_cpu) if rec_cpu is not None else None,
                current_memory_request=str(cur_mem) if cur_mem is not None else None,
                recommended_memory_request=str(rec_mem) if rec_mem is not None else None,
            )
            
            payload_batch.append(item.model_dump())

        if not payload_batch:
            log.warning("No recommendations parsed from KRR data.")
            return []

        log.info(f"Parsed {len(payload_batch)} recommendations.")

        batch = KRRBatchPayload(recommendations=payload_batch)
        envelope = IngestionMessage(
            source_module="krr_collector",
            payload=batch.model_dump()
        )
        
        return [envelope]
