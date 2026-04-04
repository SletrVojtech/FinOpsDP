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
from registry import load_collectors, COLLECTOR_REGISTRY
import yaml



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


def _load_scheduler_config(config_path=".conf/scheduler.yml"):
    """Loads and parses the scheduler configuration file."""
    if not os.path.exists(config_path):
        log.warning(f"Scheduler config not found at {config_path}")
        return {}
    with open(config_path, 'r') as f:
        return yaml.safe_load(f) or {}

def _register_scheduled_job(name, func, conf):
    """
    Registers a single job using the provided schedule configuration.
    Based on https://python.plainenglish.io/building-an-intelligent-task-scheduler-in-python-my-journey-to-automating-the-chaos-3cd258eaab97
    """
    kwargs = conf.get("kwargs", {})

    # Time-based execution
    if "time" in conf:
        schedule.every().day.at(conf["time"]).do(func, **kwargs)
        log.info(f"Registered '{name}' to run daily at {conf['time']}")
        return

    # Interval-based execution (hours, minutes, days, weeks, months)
    if "unit" in conf:
        unit = conf["unit"]
        interval = conf.get("interval", 1) # Default to 1 if not specified

        # Special workaround wrapper for 'months'
        if unit == "months":
            def run_monthly(*args, **kwargs_inner):
                import datetime
                if datetime.datetime.now().day == conf.get("day_of_month", 1):
                    func(*args, **kwargs_inner)
            
            schedule.every().day.at(conf.get("at", "00:30")).do(run_monthly, **kwargs)
            log.info(f"Registered '{name}' to run monthly on day {conf.get('day_of_month', 1)}")
            return
            
        # Dynamically fetch standard schedule unit (hours, minutes, days, weeks)
        job = schedule.every(interval)
        if hasattr(job, unit):
            job = getattr(job, unit)
        else:
            log.warning(f"Unsupported schedule unit '{unit}' for '{name}'")
            return
            
        if "at" in conf and unit in ["days", "weeks"]:
            job = job.at(conf["at"])
            
        job.do(func, **kwargs)
        log.info(f"Registered '{name}' to run every {interval} {unit}")
        return

    log.warning(f"Invalid schedule configuration for '{name}': {conf}")

def run_scheduler():
    log.info("Initializing scheduler from configuration...")

    sched_config = _load_scheduler_config()
    schedules = sched_config.get("schedules", {})
    
    # Iterate through dynamically loaded collectors and check if they have a schedule
    for name, metadata in COLLECTOR_REGISTRY.items():
        if name not in schedules:
            continue
            
        _register_scheduled_job(name, metadata["func"], schedules[name])

    if not schedule.get_jobs():
        log.warning("No jobs were scheduled!")
        
    log.info("Scheduler started")
    while True:
        schedule.run_pending()
        time.sleep(60)

def main():
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
            
    elif args.command == "scheduler":
        try:
            run_scheduler()
        except KeyboardInterrupt:
            log.info("Closing...")
            
    elif args.command in COLLECTOR_REGISTRY:
        log.info(f"Running collector: {args.command}")
        kwargs = vars(args).copy()
        kwargs.pop("command", None)
        try:
            COLLECTOR_REGISTRY[args.command]["func"](**kwargs)
            log.info("Done.")
        except KeyboardInterrupt:
            log.info("Closing...")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()