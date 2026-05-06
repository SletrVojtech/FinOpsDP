"""
Kubernetes Collection Orchestrator.

This script manages the execution of the Kubernetes metrics collector across
configured clusters and publishes the results to RabbitMQ.
"""

import logging
import os
from kube_collector.kube_collector import KubePrometheusCollector
from rabbitmq.connector import RabbitMQClient
from registry import register_collector

log = logging.getLogger("kube_runner")


@register_collector("kube", help_text="Download from Kubernetes and send to RMQ", cli_args=[("--hours", {"type": int, "default": 24, "help": "Time window to download data from"})])
def run_kube_collection(config_path: str = ".conf/kube_clusters.yml", hours: int = 24):
    """
    Run Prometheus collector across kubernetes clusters.

    Args:
        config_path (str, optional): Path to the kube_clusters.yml config. Defaults to ".conf/kube_clusters.yml".
        hours (int, optional): Number of hours of metrics to collect. Defaults to 24.
    """
    if not os.path.exists(config_path):
        log.error(f"Config file {config_path} not found.")
        return

    log.info(f"Running KubePrometheusCollector.")
    
    collector = KubePrometheusCollector(config_path=config_path, hours_back=hours)
    messages = collector.collect_all()
    
    if not messages:
        log.info("No data to send.")
        return

    log.info(f"Created {len(messages)} messages to send.")
    
    try:
        with RabbitMQClient() as rmq:
            for msg in messages:
                rmq.publish(
                    queue_name="data_ingestion", 
                    message=msg.model_dump_json()
                )
        log.info(f"Successfully sent{len(messages)} Kubernetes sets to RabbitMQ.")
        
    except Exception as e:
        log.error(f"Critical error during sending to RabbitMQ: {e}", exc_info=True)

if __name__ == "__main__":
    run_kube_collection()