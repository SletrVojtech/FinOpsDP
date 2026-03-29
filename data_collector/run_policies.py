import argparse
import logging
import os
import psycopg2
import pika
import schedule
import time
from dotenv import load_dotenv


load_dotenv()

level = logging.INFO
logging.basicConfig(
    level=level,
    format="%(asctime)s: %(name)s:%(levelname)s %(message)s",
    force=True)

logging.getLogger().setLevel(level)
logging.getLogger('pika').setLevel(logging.ERROR)
logging.getLogger('azure').setLevel(logging.ERROR)
log = logging.getLogger("finops_cli")
log.handlers.clear()

from db_loader.db_loader import DBLoader
from metrics_collector.run_collection import run_metrics_collector
from kube_collector.run_collection import run_kube_collection
from cost_collector.run_collection import run_cost_downloads
from metrics_collector.config_parser import ConfigParser
from catalog_collector.run_collection import run_catalog_collector







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
            host=os.getenv("RMQ_HOST", "rabbitmq"),
            port=int(os.getenv("RMQ_PORT", 5672)),
            credentials=credentials
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue="data_ingestion", durable=True)
    return connection, channel


def run_scheduler():
    log.info("Running scheduler")

    schedule.every(1).hours.do(run_metrics_collector)
    
    #schedule.every().day.at("01:00").do(run_kube_collection, hours_back=120)

    schedule.every().day.at("03:00").do(run_cost_downloads)
    schedule.run_all()
    log.info("Scheduler started")
    while True:
        schedule.run_pending()
        time.sleep(60)

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
    # Catalog Collector
    subparsers.add_parser("catalogs", help="Download catalogs")

    # Scheduler
    subparsers.add_parser("scheduler", help="Run scheduler")
        # Scheduler
    subparsers.add_parser("parser", help="Run scheduler")


    args = parser.parse_args()

    if args.command == "loader":
        log.info("DB loader")
        db_conn = get_db_connection()
        mq_conn, mq_channel = get_mq_channel()
        try:
            loader = DBLoader(db_conn, mq_channel)
            loader.start_consuming(queue_name="data_ingestion")
        except KeyboardInterrupt:
            log.info("Closing")
        finally:
            db_conn.close()
            mq_conn.close()

    elif args.command == "kube":
        log.info(f"Kube collector (history: {args.hours}h)")
        run_kube_collection(hours_back=args.hours)
        log.info("Done.")

    elif args.command == "costs":
        log.info("Cloud Billing API download...")
        run_cost_downloads()
        log.info("Done.")

    elif args.command == "metrics":
        log.info("Running metrics collection (using Custodian)")
        run_metrics_collector()
        log.info("Done.")
    elif args.command == "catalogs":
        log.info("Running catalog collection")
        run_catalog_collector()
        log.info("Done.")
    elif args.command == "scheduler":
        try:
            run_scheduler()
        except KeyboardInterrupt:
            log.info("Closing...")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()