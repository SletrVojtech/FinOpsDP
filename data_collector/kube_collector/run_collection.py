import logging
import os
from kube_collector.kube_collector import KubePrometheusCollector
from rabbitmq.connector import RabbitMQClient

log = logging.getLogger("kube_runner")

from registry import register_collector

@register_collector("kube", help_text="Download from Kubernetes and send to RMQ", cli_args=[("--hours", {"type": int, "default": 240, "help": "Time window to download data from"})])
def run_kube_collection(config_path: str = ".conf/kube_clusters.yml", hours_back: int = 24):
    """
    Run Prometheus collector across kubernetes clusters.
    """
    if not os.path.exists(config_path):
        log.error(f"Config file {config_path} not found.")
        return

    log.info(f"Running KubePrometheusCollector.")
    
    collector = KubePrometheusCollector(config_path=config_path, hours_back=hours_back)
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