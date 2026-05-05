import duckdb
import logging
from datetime import datetime, timedelta, timezone
from cost_collector.message import CostBatchPayload
from rabbitmq.message import IngestionMessage
from cost_collector.message_adapter import FocusCostAdapter


log = logging.getLogger("cost_loader")

class CostDataLoader:
    """
    Uses DUCKDB in-memory querying over downloaded files and batch uploads aggregated data to RabbitMQ.
    """
    def __init__(self, rmq_client, queue_name="data_ingestion"):
        self.rmq_client = rmq_client
        self.queue_name = queue_name
        self.con = duckdb.connect(database=':memory:')

    def _get_normal_charges(self, export_folder_pattern: str, cutoff_date: str) -> list[dict]:
        """Retrieve 1 day cost records"""
        query = f"""
            SELECT 
                ProviderName,
                BillingAccountId,
                BillingAccountName,
                SubAccountId,
                SubAccountName,
                RegionId,
                COALESCE(ResourceId, SubAccountId || ':general') AS resource_id,

                ServiceCategory,
                ServiceName,
                SkuPriceId,
                BillingCurrency,
                
                CAST(ChargePeriodStart AS TIMESTAMP) AS charge_period_start,

                ANY_VALUE(ResourceName) AS ResourceName,
                ANY_VALUE(ResourceType) AS ResourceType,
                ANY_VALUE(Tags) AS Tags,
                MAX(CAST(ChargePeriodEnd AS TIMESTAMP)) AS charge_period_end,
                
                SUM(EffectiveCost) AS billed_cost
            FROM read_csv_auto('{export_folder_pattern}', header=True)
            WHERE EffectiveCost != 0 AND ChargeCategory != 'Credit'
            AND CAST(ChargePeriodStart AS TIMESTAMP) >= CAST('{cutoff_date}' AS TIMESTAMP)
            AND date_diff('day', CAST(ChargePeriodStart AS DATE), CAST(ChargePeriodEnd AS DATE)) <= 1
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
        """
        return self.con.execute(query).fetchdf().to_dict('records')

    def _get_multiday_charges(self, export_folder_pattern: str, cutoff_date: str) -> list[dict]:
        """Retrieve multi-day cost records"""
        query = f"""
            SELECT 
                ProviderName,
                BillingAccountId,
                BillingAccountName,
                SubAccountId,
                SubAccountName,
                RegionId,
                COALESCE(ResourceId, SubAccountId || ':general') AS resource_id,

                ServiceCategory,
                ServiceName,
                SkuPriceId,
                BillingCurrency,
                
                CAST(ChargePeriodStart AS TIMESTAMP) AS charge_period_start,

                ANY_VALUE(ResourceName) AS ResourceName,
                ANY_VALUE(ResourceType) AS ResourceType,
                ANY_VALUE(Tags) AS Tags,
                MAX(CAST(ChargePeriodEnd AS TIMESTAMP)) AS charge_period_end,
                
                SUM(EffectiveCost) AS billed_cost
            FROM read_csv_auto('{export_folder_pattern}', header=True)
            WHERE EffectiveCost != 0 AND ChargeCategory != 'Credit'
            AND CAST(ChargePeriodEnd AS TIMESTAMP) > CAST('{cutoff_date}' AS TIMESTAMP)
            AND date_diff('day', CAST(ChargePeriodStart AS DATE), CAST(ChargePeriodEnd AS DATE)) > 1
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
        """
        return self.con.execute(query).fetchdf().to_dict('records')

    def _distribute_multiday_charges(self, multiday_dicts: list[dict], cutoff_date: str) -> list[dict]:
        """Distribute multi-day charges to daily records"""
        records = []
        cutoff_dt = datetime.strptime(cutoff_date, '%Y-%m-%d %H:%M:%S')
        
        for row in multiday_dicts:
            start_dt = row['charge_period_start']
            end_dt = row['charge_period_end']
            end_dt = min(end_dt, datetime.now(timezone.utc).replace(tzinfo=None))
            
            days_span = (end_dt - start_dt).days
            if days_span > 0:
                daily_cost = row['billed_cost'] / days_span
                for i in range(days_span):
                    current_date = start_dt + timedelta(days=i)
                    
                    new_row = dict(row)
                    new_row['charge_period_start'] = current_date
                    new_row['charge_period_end'] = current_date + timedelta(days=1)
                    new_row['billed_cost'] = daily_cost
                    records.append(FocusCostAdapter(new_row).to_payload())
        return records

    def _publish_batches(self, records: list[dict], batch_size: int):
        """Publish records to RabbitMQ in batches"""
        total_records = len(records)
        for i in range(0, total_records, batch_size):
            batch_records = records[i:i + batch_size]
            
            payload = CostBatchPayload(
                records=batch_records
            )

            message = IngestionMessage(
                source_module="cost_export",
                payload=payload.model_dump()
            )
            
            self.rmq_client.publish(
                queue_name=self.queue_name, 
                message=message.model_dump_json()
            )
        
        batches = (total_records + batch_size - 1) // batch_size
        log.info(f"Sent {total_records} records to RabbitMQ in {batches} batches.")

    def process_and_publish(self, export_folder_pattern: str, batch_size: int = 1000, days_back: int = 7):
        """Process and publish cost records to RabbitMQ"""
        log.info(f"Running DuckDB on files: {export_folder_pattern}")
        cutoff_date = ((datetime.now(timezone.utc)) - timedelta(days=days_back)).strftime('%Y-%m-%d 00:00:00')
        
        try:
            normal_dicts = self._get_normal_charges(export_folder_pattern, cutoff_date)
            multiday_dicts = self._get_multiday_charges(export_folder_pattern, cutoff_date)
            
            log.info(f"DuckDB aggregation completed. {len(normal_dicts)} normal, {len(multiday_dicts)} multiday records.")

            if not normal_dicts and not multiday_dicts:
                return
            
            records = []
            for row in normal_dicts:
                records.append(FocusCostAdapter(row).to_payload())
                
            records.extend(self._distribute_multiday_charges(multiday_dicts, cutoff_date))
            
            if records:
                self._publish_batches(records, batch_size)
                
        except Exception as e:
            log.error(f"Error during DuckDB aggregation: {e}", exc_info=True)