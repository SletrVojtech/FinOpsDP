"""
Job Scheduler Module.

This module provides the Scheduler class, which manages the periodic execution
of data collection jobs based on a YAML configuration file.
"""

import logging
import os
import time
import datetime
from typing import Dict, Any, Optional, Callable
import yaml
import schedule

log = logging.getLogger(__name__)


class Scheduler:
    """
    A job scheduling manager for data collection modules.

    This class reads configuration from a YAML file and dynamically maps
    schedules to registered collector functions using the `schedule` library.

    Attributes:
        collector_registry (dict): A dictionary containing loaded collectors and their metadata.
        config_path (str): The file path to the YAML configuration file.
    """

    def __init__(self, collector_registry: dict, config_path=".conf/scheduler.yml"):
        """
        Initializes the Scheduler instance.

        Args:
            collector_registry (dict): Registry containing available collector modules.
            config_path (str, optional): Path to the schedule configuration file. 
                                         Defaults to ".conf/scheduler.yml".
        """
        self.collector_registry = collector_registry
        self.config_path = config_path
    
    def _load_scheduler_config(self) -> dict:
        """
        Loads and parses the scheduler configuration file.
        
        Returns:
            dict: The parsed configuration as a dictionary. Returns an empty 
                  dictionary if the file is not found or is unreadable.
        """
        if not os.path.exists(self.config_path):
            log.warning(f"Scheduler config not found at {self.config_path}")
            return {}
        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            log.error(f"Failed to parse YAML config at {self.config_path}: {e}")
            return {}

    def _register_scheduled_job(self, name, func, conf) -> None:
        """
        Registers a single job using the provided schedule configuration.
        Based on https://python.plainenglish.io/building-an-intelligent-task-scheduler-in-python-my-journey-to-automating-the-chaos-3cd258eaab97

        Supports time-based execution (e.g., daily at a specific time) and 
        interval-based execution (hours, minutes, days, weeks, months).

        Args:
            name (str): The name of the registered collector/job.
            func (callable): The function to be executed by the scheduler.
            conf (dict): The configuration dictionary for the specific job, 
                         containing scheduling parameters (e.g., 'time', 'unit', 'interval').
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

    def run_scheduler(self) -> None:
        """
        Initializes the schedules and starts the blocking scheduler loop.

        Iterates through the collector registry, applies the schedules from the 
        configuration, and continuously runs pending jobs. 
        """
        log.info("Initializing scheduler from configuration")

        sched_config = self._load_scheduler_config()
        schedules = sched_config.get("schedules", {})
    
        # Iterate through dynamically loaded collectors and check if they have a schedule
        for name, metadata in self.collector_registry.items():
            if name not in schedules:
                continue
                
            self._register_scheduled_job(name, metadata["func"], schedules[name])

        if not schedule.get_jobs():
            log.warning("No jobs were scheduled!")
        
        log.info("Scheduler started")
        while True:
            try:
                schedule.run_pending()
            except Exception as e:
                log.error(f"Error running pending jobs: {e}")
            time.sleep(60)