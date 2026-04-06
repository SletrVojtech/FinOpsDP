import logging
import os
import sys
import yaml
import json
from krr_collector.krr_parser import KRRFileParser
from rabbitmq.connector import RabbitMQClient
from dotenv import load_dotenv
load_dotenv()
import subprocess

def get_kubeconfig_path():
    path = os.getenv("KUBECONFIG_PATH")
    if not path:
        logging.critical("KUBECONFIG_PATH env-var is not set.")
    return path


log = logging.getLogger("krr_file_parser")
logging.getLogger('pika').setLevel(logging.ERROR)

def run_krr_for_context(context_name: str):
    """Runs a KRR docker image to get a json with recommendations."""
    kubeconfig = get_kubeconfig_path()
    if not kubeconfig: return None

    log.info(f"Running KRR for context: {context_name}")
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{kubeconfig}:/root/.kube/config:ro",
        "us-central1-docker.pkg.dev/genuine-flight-317411/devel/krr:v1.8.3",
        "python","krr.py", "simple", "--context", context_name, "-f", "json", "-q"
    ]

    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        log.error(f"KRR container failed for context {context_name}. Error: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        log.error(f"Unable to parse JSON output for context{context_name}. Error: {e}")
        return None


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    try:
        with open(".conf/kube_clusters.yml", 'r') as f:
            config = yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError) as e:
        log.error(f"Failed to load KRR config: {e}")
        return


    messages = []
    for idx,cluster in enumerate(config.get('clusters', [])):

        try:
            parser = KRRFileParser(krr_data=run_krr_for_context(context_name=cluster['context']), cluster_info=cluster)
            messages.extend(parser.parse_to_rabbitmq())
        except Exception as e:
                log.error(f"Error during processing cluster {cluster.get('cluster_name')}: {e}", exc_info=True)

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
    main()