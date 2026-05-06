"""
FinOps Central Collector CLI.

This script serves as the main entry point for the data collection pipeline.
It provides a command-line interface to:
- Run the database loader (RabbitMQ to PostgreSQL).
- Start the job scheduler for periodic data collection.
- Manually trigger specific data collectors (AWS, Azure, etc.).
"""

import argparse
import logging
import os
import psycopg2
import pika

from dotenv import load_dotenv

load_dotenv()
log = setup_logging()

from db_loader.db_loader import DBLoader
from scheduler import Scheduler
from registry import load_collectors, COLLECTOR_REGISTRY

def setup_logging() -> logging.Logger:
    """
    Sets up the global logging configuration for the collector application.

    Returns:
        logging.Logger: The configured logger instance.
    """
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
    return log


def get_db_connection() -> psycopg2.connection:
    """
    Builds a connection to the PostgreSQL database.
    Requires DB_HOST, DB_USER, DB_PASSWORD, and DB_NAME to be set.

    Returns:
        psycopg2.connection: A connection object to the database.

    Raises:
        RuntimeError: If any of the required environment variables are not set.
        psycopg2.Error: If the database connection fails.
    """
    for var in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        if not os.getenv(var):
            raise RuntimeError(f"Missing required env-var: {var}")
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.getenv("DB_PORT", "5432"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"]
    )

def get_mq_channel() -> tuple:
    """
    Establishes a connection to RabbitMQ and declares the required queue.

    Reads RabbitMQ credentials from environment variables. Ensures that the
    'data_ingestion' queue exists and is durable.

    Returns:
        tuple: A tuple containing:
            - pika.BlockingConnection: The active RabbitMQ connection.
            - pika.adapters.blocking_connection.BlockingChannel: The channel object.

    Raises:
        RuntimeError: If RMQ_USER or RMQ_PASSWORD environment variables are missing.
        pika.exceptions.AMQPConnectionError: If the connection to RabbitMQ fails.
    """
    for var in ("RMQ_USER", "RMQ_PASSWORD"):
        if not os.getenv(var):
            raise RuntimeError(f"Missing required env-var: {var}")
    credentials = pika.PlainCredentials(
        os.environ["RMQ_USER"],
        os.environ["RMQ_PASSWORD"]
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




def main():
    """
    Main entry point for the FinOps central collector CLI.

    Parses command-line arguments and routes execution to the appropriate
    module, such as the DB loader, the job scheduler, or a dynamically
    loaded data collector.
    """
    load_collectors()

    parser = argparse.ArgumentParser(description="FinOps central collector CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available modules:")

    # DB loader
    subparsers.add_parser("loader", help="DB loader between RabbitMQ and PostgreSQL")

    # Scheduler
    subparsers.add_parser("scheduler", help="Run scheduler")

    # Dynamic Modules
    for name, metadata in COLLECTOR_REGISTRY.items():
        cmd_parser = subparsers.add_parser(name, help=metadata["help"])
        for arg_name, arg_kwargs in metadata["cli_args"]:
            cmd_parser.add_argument(arg_name, **arg_kwargs)

    args = parser.parse_args()

    if args.command == "loader":
        log.info("DB loader starting")
        db_conn = None
        mq_conn = None
        try:
            db_conn = get_db_connection()
            mq_conn, mq_channel = get_mq_channel()
            loader = DBLoader(db_conn, mq_channel)
            loader.start_consuming(queue_name="data_ingestion")
        except KeyboardInterrupt:
            log.info("Closing (KeyboardInterrupt)")
        except Exception as e:
            log.error(f"Failed to start loader: {e}", exc_info=True)
        finally:
            if db_conn:
                db_conn.close()
            if mq_conn:
                mq_conn.close()
            
    elif args.command == "scheduler":
        try:
            scheduler = Scheduler(COLLECTOR_REGISTRY)
            scheduler.run_scheduler()
        except KeyboardInterrupt:
            log.info("Closing")
            
    elif args.command in COLLECTOR_REGISTRY:
        log.info(f"Running collector: {args.command}")
        kwargs = vars(args).copy()
        kwargs.pop("command", None)
        try:
            COLLECTOR_REGISTRY[args.command]["func"](**kwargs)
            log.info("Done.")
        except KeyboardInterrupt:
            log.info("Closing")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()