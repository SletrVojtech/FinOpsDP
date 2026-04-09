import json
import os
import sys
from rabbitmq.message import IngestionMessage
from catalog_collector.pricing_collector import AWSPricingDownloader, AzurePricingDownloader
from catalog_collector.hardware_collector import AWSHardwareDownloader, AzureHardwareDownloader
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from rabbitmq.connector import RabbitMQClient
from catalog_collector.message import PricingRecord
from typing import List

load_dotenv()



def deduplicate_pricing_records(pricing_records: List[PricingRecord]) -> List[PricingRecord]:
    """
        Deduplicate the pricing records on DB primary Key.
    """
    unique_records = {}
    
    for record in pricing_records:
        # Needs to be in sych with DB_loader
        pk = (record.cloud, record.instance_type, record.region, record.os)
        
        if pk not in unique_records:
            unique_records[pk] = record
        else:
            # Save the cheapest one
            if record.hourly_price_usd < unique_records[pk].hourly_price_usd:
                unique_records[pk] = record
                
    return list(unique_records.values())


from registry import register_collector

@register_collector("catalogs", help_text="Download catalogs")
def run_catalog_collector():

    _AZURE_SUB_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
    if not _AZURE_SUB_ID:
        sys.exit("[catalog_collector] Missing required env-var: AZURE_SUBSCRIPTION_ID")
    
    aws_hw = AWSHardwareDownloader()
    aws_price = AWSPricingDownloader()

    credential = DefaultAzureCredential()
    token = credential.get_token("https://management.azure.com/.default").token
    
    azure_hw = AzureHardwareDownloader(_AZURE_SUB_ID, token)
    azure_price = AzurePricingDownloader()
    
    # Get HW info
    print("Fetching Hardware")
    all_hw = aws_hw.fetch_hardware() + azure_hw.fetch_hardware()
    
    # Get Price info
    print("Fetching Pricing")
    all_pricing = deduplicate_pricing_records(aws_price.fetch_pricing()) + deduplicate_pricing_records(azure_price.fetch_pricing())
    

    payload_dict = {
        "hardware_records": all_hw,
        "pricing_records": all_pricing
    }
    
    message = IngestionMessage(
        source_module="catalog_downloader",
        payload=payload_dict
    )
    with RabbitMQClient() as rmq:
        len_hw = len(all_hw)
        len_price = len(all_pricing)
        id_hw = 0
        id_price = 0

        while id_hw < len_hw:
            max_id_hw = min(id_hw + 1000, len_hw)
            payload_dict = {
                "hardware_records": all_hw[id_hw:max_id_hw],
            }
            message = IngestionMessage(
                source_module="catalog_downloader",
                payload=payload_dict
            )
            rmq.publish(
                queue_name="data_ingestion", 
                message=message.model_dump_json()
            )
            id_hw = max_id_hw
        
        while id_price < len_price:
            max_id_price = min(id_price + 1000, len_price)
            payload_dict = {
                "pricing_records": all_pricing[id_price:max_id_price],
            } 
            message = IngestionMessage(
                source_module="catalog_downloader",
                payload=payload_dict
            )
            rmq.publish(
                queue_name="data_ingestion", 
                message=message.model_dump_json()
            )
            id_price = max_id_price


if __name__ == "__main__":
    run_catalog_collector()