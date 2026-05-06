"""
Database Initialization Module.

This module provides the DatabaseInitializer class, which is responsible for
creating the base schema, setting up TimescaleDB hypertables, and configuring
continuous aggregate hierarchies for metric data.
"""

import psycopg2
import yaml
import logging
import os
import time
from typing import Dict, Any, Tuple, List, Optional
from dotenv import load_dotenv
from table_templates import SCHEMA_DEFINITIONS, cagg_first_metrics,cagg_next_metrics

load_dotenv()
log = logging.getLogger("db_init")


class DatabaseInitializer:
    """
    Handles the initialization and configuration of the FinOps database.
    """
    def __init__(self, config_path: str):
        """
        Initialize the database connection and load configuration.

        Args:
            config_path (str): Path to the db_config.yml file.

        Raises:
            RuntimeError: If the database connection fails after several retries.
        """
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        max_retries = 5
        retry_delay = 3
        
        self.conn = None
        for attempt in range(max_retries):
            try:
                self.conn = psycopg2.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    port=os.getenv("DB_PORT", "5432"),
                    user=os.getenv("DB_USER", "finops"),
                    password=os.getenv("DB_PASSWORD", "finops_password"),
                    database=os.getenv("DB_NAME", "finops_db")
                )
                break
            except psycopg2.OperationalError as e:
                if attempt < max_retries - 1:
                    log.warning(f"Database connection attempt {attempt + 1} failed. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    log.critical("Critical error: Could not connect to the database.")
                    raise RuntimeError(f"Database connection failed: {e}")

        if self.conn:
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()

    def check_table_exists(self, table_name: str) -> bool:
        """
        Checks if a table exists in the public schema.

        Args:
            table_name (str): The name of the table to check.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        self.cursor.execute("""
            SELECT EXISTS (
                SELECT FROM pg_tables 
                WHERE schemaname = 'public' AND tablename = %s
            );
        """, (table_name.lower(),))
        return self.cursor.fetchone()[0]

    def setup_base_tables(self):
        """
        Creates the base tables defined in table_templates if they do not exist.
        Also ensures the root entity (Id=0) exists.
        """
        log.info("Checking for existing base tables")
        for table_name, create_sql in SCHEMA_DEFINITIONS.items():
            if not self.check_table_exists(table_name):
                log.info(f"Creating table {table_name}")
                self.cursor.execute(create_sql)
            else:
                log.info(f"Table {table_name} already exists.")

        self.cursor.execute("""
        INSERT INTO Entities (Id,ExternalId) VALUES (0, 'root') ON CONFLICT (id) DO NOTHING;
        """)

    def _to_seconds(self, interval: str) -> int:
        """
        Converts a Postgres interval string ('5 minutes') to seconds.

        Args:
            interval (str): The interval string.

        Returns:
            int: Total seconds.

        Raises:
            ValueError: If the time unit is unknown.
        """
        UNIT_MULTIPLIERS = {
            'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400, 'week': 604800
        }
        parts = interval.split()
        if len(parts) < 2:
            return 0
            
        val = int(parts[0])
        unit = parts[1].lower()
        if unit.endswith('s'): 
            unit = unit[:-1]

        if unit not in UNIT_MULTIPLIERS:
            raise ValueError(f"Unknown time unit: {unit}.")
            
        return val * UNIT_MULTIPLIERS[unit]

    def upsert_dictionary_entry(self, table_name: str, data_type: str, granularity: str, 
                                 retention: str, is_cagg: bool = False):
        """
        Upserts an entry into the DataDictionary table.

        Args:
            table_name (str): Name of the table or view.
            data_type (str): Type of data (metric, cost, etc.).
            granularity (str): Time granularity of the data.
            retention (str): Retention period.
            is_cagg (bool, optional): Whether it is a Continuous Aggregate. Defaults to False.
        """
        log.info(f"Updating DataDictionary entry for '{table_name}'")
        self.cursor.execute("""
            INSERT INTO DataDictionary (TableName, DataType, Granularity, RetentionDuration, IsCagg)
            VALUES (%s, %s, %s::interval, %s::interval, %s)
            ON CONFLICT (TableName) DO UPDATE 
            SET DataType = EXCLUDED.DataType,
                Granularity = EXCLUDED.Granularity,
                RetentionDuration = EXCLUDED.RetentionDuration;
        """, (table_name.lower(), data_type, granularity, retention, is_cagg))

    def _check_time_hierarchy(self, interval: str, previous_interval: str) -> bool:
        """
        Verifies that a larger interval is a multiple of a smaller interval.

        Args:
            interval (str): The larger interval.
            previous_interval (str): The smaller (source) interval.

        Returns:
            bool: True if the hierarchy is valid.
        """
        interval_seconds = self._to_seconds(interval)
        previous_seconds = self._to_seconds(previous_interval)
        if previous_seconds == 0:
            return True
        return interval_seconds % previous_seconds == 0

    def check_cagg_exists(self, view_name: str) -> bool:
        """
        Checks if a Continuous Aggregate exists.

        Args:
            view_name (str): The name of the materialized view.

        Returns:
            bool: True if it exists.
        """
        self.cursor.execute("""
            SELECT EXISTS (
                SELECT FROM timescaledb_information.continuous_aggregates 
                WHERE view_name = %s
            );
        """, (view_name.lower(),))
        return self.cursor.fetchone()[0]

    def setup_metric_hierarchy(self):
        """
        Sets up the metric aggregation hierarchy (CAGGs) and retention policies
        based on the provided configuration.
        """
        log.info("Setting up metric aggregation hierarchy.")
        tables = self.config.get('data_hierarchy', {})
        
        for table_hierarchy_name, config in tables.items():
            # Raw data table configuration
            raw_table = config['raw_table']
            raw_retention = config.get('raw_retention')
            if raw_retention:
                self.cursor.execute(f"SELECT remove_retention_policy('{raw_table}', if_exists => true);")
                self.cursor.execute(f"SELECT add_retention_policy('{raw_table}', INTERVAL '{raw_retention}');")
                log.info(f"Retention policy added: {raw_table} to {raw_retention}")

            previous_interval = config['raw_interval']
            previous_table = raw_table

            self.upsert_dictionary_entry(raw_table, table_hierarchy_name, previous_interval, raw_retention)

            # Continuous Aggregates setup
            aggregates = config.get('aggregates', [])
            for idx, agg in enumerate(aggregates):
                view_name = agg['name']
                interval = agg['interval']
                retention = agg.get('retention')
                is_first_level = (idx == 0)
                refresh_window = agg.get('refresh_window')

                # If no refresh window provided, default to a safe lookback (e.g. 7 * interval)
                if not refresh_window:
                    val = int(interval.split()[0]) * 7
                    unit = interval.split()[1]
                    refresh_window = f"{val} {unit}"

                if not self._check_time_hierarchy(interval, previous_interval):
                    raise ValueError(f"Hierarchy error: Interval '{interval}' in '{view_name}' is not a multiple of '{previous_interval}'.")

                if not self.check_cagg_exists(view_name):
                    log.info(f"Creating CAGG {view_name} (interval: {interval}, source: {previous_table})")
                    if is_first_level:
                        sql = cagg_first_metrics(view_name, interval)
                    else:
                        sql = cagg_next_metrics(view_name, interval, previous_table)
                    self.cursor.execute(sql)
                    
                    self.cursor.execute(f"""
                        SELECT add_continuous_aggregate_policy('{view_name}',
                          start_offset => INTERVAL '{refresh_window}',
                          end_offset   => INTERVAL '{interval}',
                          schedule_interval => INTERVAL '{interval}');
                    """)
                else:
                    log.info(f"CAGG {view_name} already exists.")

                if retention:
                    self.cursor.execute(f"SELECT remove_retention_policy('{view_name}', if_exists => true);")
                    self.cursor.execute(f"SELECT add_retention_policy('{view_name}', INTERVAL '{retention}');")
                    log.info(f"Retention policy added: {view_name} to {retention}")

                self.upsert_dictionary_entry(view_name, table_hierarchy_name, interval, retention, True)
                previous_interval = interval
                previous_table = view_name

    def close(self):
        """
        Closes the database connection.
        """
        if hasattr(self, 'cursor') and self.cursor:
            self.cursor.close()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initializer = DatabaseInitializer("data_collector/db_init/db_config.yml")
    try:
        initializer.setup_base_tables()
        initializer.setup_metric_hierarchy()
        log.info("Database initialization completed successfully.")
    except Exception as e:
        log.error(f"Initialization failed: {e}")
    finally:
        initializer.close()