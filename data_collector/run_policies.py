import argparse
import logging
import os
import psycopg2
import pika
from dotenv import load_dotenv


load_dotenv()

from db_loader.db_loader import DBLoader
from metrics_collector.run_collection import run_metrics_collector
from kube_collector.run_collection import run_kube_collection
from cost_collector.run_collection import run_cost_downloads


log = logging.getLogger("finops_cli")
logging.getLogger('pika').setLevel(logging.ERROR)

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "finops"),
        password=os.getenv("DB_PASSWORD", "finops_password"),
        database=os.getenv("DB_NAME", "finops_db")
    )

def get_mq_channel():
    credentials = pika.PlainCredentials(
        os.getenv("RMQ_USER", "finops"), 
        os.getenv("RMQ_PASSWORD", "finops_password")
    )
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=os.getenv("RMQ_HOST", "localhost"),
            port=int(os.getenv("RMQ_PORT", 5672)),
            credentials=credentials
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue="data_ingestion", durable=True)
    return connection, channel

def main():
    parser = argparse.ArgumentParser(description="FinOps central collector CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available modules:")

    # DB loader
    subparsers.add_parser("loader", help="DB loader between RabbitMQ and PostgreSQL")

    # Kube Collector
    parser_kube = subparsers.add_parser("kube", help="Download from Kubernetes and send to RMQ")
    parser_kube.add_argument("--hours", type=int, default=24, help="Time window to download data from")

    # Cost Collector
    subparsers.add_parser("costs", help="Download CostExports from Cloud Billing API and send to RMQ")

    # Metrics Collector
    subparsers.add_parser("metrics", help="Download metrics using Custodian and send to RMQ")

    args = parser.parse_args()

    if args.command == "loader":
        log.info("DB loader...")
        db_conn = get_db_connection()
        mq_conn, mq_channel = get_mq_channel()
        try:
            loader = DBLoader(db_conn, mq_channel)
            loader.start_consuming(queue_name="data_ingestion")
        except KeyboardInterrupt:
            log.info("Closing...")
        finally:
            db_conn.close()
            mq_conn.close()

    elif args.command == "kube":
        log.info(f"Kube collector (history: {args.hours}h)...")
        run_kube_collection(hours_back=args.hours)
        log.info("Done.")

    elif args.command == "costs":
        log.info("Cloud Billing API download...")
        run_cost_downloads()
        log.info("Done.")

    elif args.command == "metrics":
        log.info("Running metrics collection (using Custodian)...")
        run_metrics_collector()
        log.info("Done.")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()