import psycopg2
import yaml
import logging
import os
import re
from dotenv import load_dotenv
from table_templates import SCHEMA_DEFINITIONS, cagg_first_metrics,cagg_next_metrics

load_dotenv()
log = logging.getLogger("db_init")



class DatabaseInitializer:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
            
        self.conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            user=os.getenv("DB_USER", "finops"),
            password=os.getenv("DB_PASSWORD", "finops_password"),
            database=os.getenv("DB_NAME", "finops_db")
        )
        self.conn.autocommit = True
        self.cursor = self.conn.cursor()

    def check_table_exists(self, table_name: str) -> bool:
        self.cursor.execute("""
            SELECT EXISTS (
                SELECT FROM pg_tables 
                WHERE schemaname = 'public' AND tablename = %s
            );
        """, (table_name.lower(),))
        return self.cursor.fetchone()[0]

    def setup_base_tables(self):
        log.info("Check existing tables")
        for table_name, create_sql in SCHEMA_DEFINITIONS.items():
            if not self.check_table_exists(table_name):
                log.info(f"Creating table {table_name}")
                self.cursor.execute(create_sql)
            else:
                log.info(f"Table {table_name} already exists.")

    def _to_seconds(self, interval: str) -> int:
        UNIT_MULTIPLIERS = {
        'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400, 'week': 604800
        }
        val = int(interval.split()[0]) * 7
        unit = interval.split()[1]
        if unit.endswith('s'): 
            unit = unit[:-1]

        if not UNIT_MULTIPLIERS[unit]:
            raise ValueError(f"Unknown time unit: {unit}.")
        return val * UNIT_MULTIPLIERS[unit]


    def upsert_dictionary_entry(self, table_name: str, data_type: str, granularity: str, retention: str):
        """Upsert information about retention policies for each table and CAGG"""
        log.info(f"Updating retention policy metadata for'{table_name}.'")
        self.cursor.execute("""
            INSERT INTO DataDictionary (TableName, DataType, Granularity, RetentionDuration)
            VALUES (%s, %s, %s::interval, %s::interval)
            ON CONFLICT (TableName) DO UPDATE 
            SET DataType = EXCLUDED.DataType,
                Granularity = EXCLUDED.Granularity,
                RetentionDuration = EXCLUDED.RetentionDuration;
        """, (table_name.lower(), data_type, granularity, retention))

    def _check_time_hierarchy(self, interval, previous_interval):
        interval_seconds = self._to_seconds(interval)
        previous_seconds = self._to_seconds(previous_interval)
        return interval_seconds % previous_seconds == 0


    def check_cagg_exists(self, view_name: str) -> bool:
        self.cursor.execute("""
            SELECT EXISTS (
                SELECT FROM timescaledb_information.continuous_aggregates 
                WHERE view_name = %s
            );
        """, (view_name.lower(),))
        return self.cursor.fetchone()[0]

    def setup_metric_hierarchy(self):
        log.info("Creating aggregation hierarchy.")
        tables = self.config.get('data_hierarchy', {})
        
        for table_hierarchy_name, config in tables.items():
            data_type = config.get('data_type', 'metric')
            
            # Set up retention for raw data table
            raw_table = config['raw_table']
            raw_retention = config.get('raw_retention')
            if raw_retention:
                self.cursor.execute(f"SELECT remove_retention_policy('{raw_table}', if_exists => true);")
                self.cursor.execute(f"SELECT add_retention_policy('{raw_table}', INTERVAL '{raw_retention}');")
                log.info(f"Retention set: {raw_table} to {raw_retention}")

            previous_interval = config['raw_interval']
            previous_table = raw_table

            self.upsert_dictionary_entry(raw_table, data_type, previous_interval, raw_retention)


            # Aggregates            
            aggregates = config.get('aggregates', [])
            for idx, agg in enumerate(aggregates):
                view_name = agg['name']
                interval = agg['interval']
                retention = agg.get('retention')
                is_first_level = (idx == 0)
                refresh_window = agg.get('refresh_window')

                if not refresh_window:
                        val = int(interval.split()[0]) * 7
                        unit = interval.split()[1]
                        refresh_window = f"{val} {unit}"
                # Check if cagg interval can be used.
                if not self._check_time_hierarchy(interval, previous_interval):
                    raise ValueError(f"Hierarchy error: Interval '{interval}' in '{view_name}' isn't a multiple of '{previous_interval}'.")

                # Create if doesn't exist.
                if not self.check_cagg_exists(view_name):
                    log.info(f"Creating CAGG {view_name} (interval: {interval}, on top of: {previous_table})")
                    if is_first_level:
                        sql = cagg_first_metrics(view_name, interval)
                    else:
                        sql = cagg_next_metrics(view_name, interval, previous_table)
                    self.cursor.execute(sql)
                    # Set the refresh policy.
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
                    log.info(f"Retention set to {retention}")

                self.upsert_dictionary_entry(view_name, data_type, interval, retention)
                previous_interval = interval
                previous_table = view_name

    def close(self):
        self.cursor.close()
        self.conn.close()

if __name__ == "__main__":
    initializer = DatabaseInitializer("db_init/db_config.yml")
    try:
        initializer.setup_base_tables()
        log.info("DB setup finished.")
        initializer.setup_metric_hierarchy()
        log.info("DB setup finished.")
    except Exception as e:
        log.error(f"Error: {e}")
    finally:
        initializer.close()