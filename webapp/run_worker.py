#!/usr/bin/env python3
import sys
import logging
import argparse
from jobs.fbad_worker.anomaly_job import run_anomaly_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('run_worker')

def main():
    parser = argparse.ArgumentParser(description="Trigger FinOps FBAD worker")
    parser.add_argument("--job", type=str, required=True, choices=["fbad"], help="Name of the job to run")
    
    args = parser.parse_args()
    
    if args.job == "fbad":
        logger.info("Triggering Forecast-Based Anomaly Detection job manually.")
        try:
            run_anomaly_job()
            logger.info("Job finished successfully.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Job failed with error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
