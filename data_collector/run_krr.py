"""
KRR Collection Orchestrator.

This script manages the execution of the Robusta KRR tool across multiple Kubernetes
clusters and publishes the resulting recommendations to RabbitMQ for ingestion.
"""

import logging
import os
import sys
import yaml
import json
import subprocess
from typing import Optional, Any, Dict
from dotenv import load_dotenv

from krr_collector.krr_parser import KRRFileParser
from rabbitmq.connector import RabbitMQClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger("krr_file_parser")
logging.getLogger('pika').setLevel(logging.ERROR)


def get_kubeconfig_path() -> Optional[str]:
    """
    Retrieves the KUBECONFIG_PATH from environment variables.

    Returns:
        Optional[str]: The path to the kubeconfig file, or None if not set.
    """
    path = os.getenv("KUBECONFIG_PATH")
    if not path:
        log.error("KUBECONFIG_PATH environment variable is not set.")
    return path


def run_krr_for_context(context_name: str) -> Optional[Dict[str, Any]]:
    """
    Runs the KRR tool for a specific Kubernetes context.

    Args:
        context_name (str): The name of the Kubernetes context to scan.

    Returns:
        Optional[Dict[str, Any]]: The parsed JSON output from KRR, or None if the run failed.
    """
    kubeconfig = get_kubeconfig_path()
    if not kubeconfig:
        return None
        
    # Command to execute KRR 
    cmd = ["python", "/app/krr.py", "simple", "--context", context_name, "-f", "json", "-q"]
    log.info(f"Running KRR for context: {context_name}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        log.error(f"KRR tool failed for context {context_name}. Error: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        log.error(f"Unable to parse JSON output for context {context_name}. Error: {e}")
        return None


def main():
    """
    Main orchestration function for KRR data collection across configured clusters.
    """
    config_path = ".conf/kube_clusters.yml"
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError) as e:
        log.error(f"Failed to load KRR config from {config_path}: {e}")
        return

    clusters = config.get('clusters', [])
    if not clusters:
        log.info("No clusters configured in the config file.")
        return

    try:
        with RabbitMQClient() as rmq:
            for cluster in clusters:
                cluster_name = cluster.get('cluster_name', 'unknown')
                try:
                    krr_data = run_krr_for_context(context_name=cluster['context'])
                    if not krr_data:
                        continue
                        
                    parser = KRRFileParser(krr_data=krr_data, cluster_info=cluster)
                    messages = parser.parse_to_rabbitmq()
                    
                    if not messages:
                        log.info(f"No recommendations found for cluster {cluster_name}.")
                        continue

                    for msg in messages:
                        rmq.publish(
                            queue_name="data_ingestion", 
                            message=msg.model_dump_json()
                        )
                    log.info(f"Successfully sent KRR recommendations for cluster {cluster_name} to RabbitMQ.")
                    
                except Exception as e:
                    log.error(f"Error during processing cluster {cluster_name}: {e}", exc_info=True)
                    
    except Exception as e:
        log.error(f"Critical error during RabbitMQ interaction: {e}", exc_info=True)


if __name__ == "__main__":
    main()