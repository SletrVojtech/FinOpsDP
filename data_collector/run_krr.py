import logging
import yaml
from krr_collector.krr_parser import KRRFileParser
from rabbitmq.connector import RabbitMQClient
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger("krr_file_parser")
logging.getLogger('pika').setLevel(logging.ERROR)



def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    with open(".conf/kube_clusters.yml", 'r') as f:
        config = yaml.safe_load(f)
    files = ["data_collector/krr_collector/tmp/aws_krr.json","data_collector/krr_collector/tmp/azure_krr.json"]
    messages = []
    for idx,cluster in enumerate(config.get('clusters', [])):
        try:
            parser = KRRFileParser(json_filepath=files[idx], cluster_info=cluster)
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