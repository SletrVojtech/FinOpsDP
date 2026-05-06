"""
Catalog Collection Module.

This module is responsible for orchestrating the collection of cloud provider
hardware specifications and pricing catalogs. It downloads these datasets for
supported providers (AWS, Azure) and pushes them to the ingestion queue.
"""

import os
from typing import List, Any

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

from rabbitmq.connector import RabbitMQClient
from rabbitmq.message import IngestionMessage
from catalog_collector.pricing_collector import AWSPricingDownloader, AzurePricingDownloader
from catalog_collector.hardware_collector import AWSHardwareDownloader, AzureHardwareDownloader
from catalog_collector.message import PricingRecord
from registry import register_collector

load_dotenv()


def deduplicate_pricing_records(pricing_records: List[PricingRecord]) -> List[PricingRecord]:
    """
    Deduplicate the pricing records based on the database primary key.

    Args:
        pricing_records (List[PricingRecord]): A list of raw pricing records fetched from the provider.

    Returns:
        List[PricingRecord]: A list of deduplicated pricing records, keeping the cheapest options.
    """
    unique_records = {}
    
    for record in pricing_records:
        # Needs to be in synch with DB_loader
        pk = (record.cloud, record.instance_type, record.region, record.os)
        
        if pk not in unique_records:
            unique_records[pk] = record
        else:
            # Save the cheapest one
            if record.hourly_price_usd < unique_records[pk].hourly_price_usd:
                unique_records[pk] = record
                
    return list(unique_records.values())


def chunk_and_publish(rmq: RabbitMQClient, records: List[Any], record_type: str, chunk_size: int = 1000) -> None:
    """
    Chunk records into smaller batches and publish them to the RabbitMQ data ingestion queue.
    
    Args:
        rmq (RabbitMQClient): The connected RabbitMQ client instance.
        records (List[Any]): A list of records (hardware or pricing) to be published.
        record_type (str): The key used in the payload dictionary (e.g., 'hardware_records').
        chunk_size (int, optional): The maximum number of records per message chunk.
    """
    total_len = len(records)
    current_idx = 0
    
    while current_idx < total_len:
        next_idx = min(current_idx + chunk_size, total_len)
        payload_dict = {
            record_type: records[current_idx:next_idx],
        }
        message = IngestionMessage(
            source_module="catalog_downloader",
            payload=payload_dict
        )
        rmq.publish(
            queue_name="data_ingestion", 
            message=message.model_dump_json()
        )
        current_idx = next_idx


@register_collector("catalogs", help_text="Download catalogs")
def run_catalog_collector() -> None:
    """
    Execute the full catalog collection process.

    This function authenticates with cloud providers, fetches hardware and
    pricing datasets, deduplicates pricing information, and queues the
    results in RabbitMQ for database ingestion.

    Raises:
        ValueError: If the AZURE_SUBSCRIPTION_ID environment variable is missing.
    """
    _AZURE_SUB_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
    if not _AZURE_SUB_ID:
        raise ValueError("[catalog_collector] Missing required env-var: AZURE_SUBSCRIPTION_ID")
    
    aws_hw = AWSHardwareDownloader()
    aws_price = AWSPricingDownloader()

    credential = DefaultAzureCredential()
    token = credential.get_token("https://management.azure.com/.default").token
    
    azure_hw = AzureHardwareDownloader(_AZURE_SUB_ID, token)
    azure_price = AzurePricingDownloader()
    
    with RabbitMQClient() as rmq:
        # Get HW info
        print("Fetching AWS Hardware")
        aws_hw_records = aws_hw.fetch_hardware()
        chunk_and_publish(rmq, aws_hw_records, "hardware_records")
        
        print("Fetching Azure Hardware")
        azure_hw_records = azure_hw.fetch_hardware()
        chunk_and_publish(rmq, azure_hw_records, "hardware_records")
        
        # Get Price info
        print("Fetching AWS Pricing")
        aws_pricing_records = deduplicate_pricing_records(aws_price.fetch_pricing())
        chunk_and_publish(rmq, aws_pricing_records, "pricing_records")
        
        print("Fetching Azure Pricing")
        azure_pricing_records = deduplicate_pricing_records(azure_price.fetch_pricing())
        chunk_and_publish(rmq, azure_pricing_records, "pricing_records")


if __name__ == "__main__":
    run_catalog_collector()