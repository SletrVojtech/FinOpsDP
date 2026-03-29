import json
from rabbitmq.message import IngestionMessage
from catalog_collector.pricing_collector import AWSPricingDownloader, AzurePricingDownloader
from catalog_collector.hardware_collector import AWSHardwareDownloader, AzureHardwareDownloader
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from rabbitmq.connector import RabbitMQClient

load_dotenv()




def run_catalog_collector():
    
    aws_hw = AWSHardwareDownloader()
    aws_price = AWSPricingDownloader()

    credential = DefaultAzureCredential()
    token = credential.get_token("https://management.azure.com/.default").token
    
    azure_hw = AzureHardwareDownloader("9e97b1e3-0905-4d1f-b923-d050f30d1204", token)
    azure_price = AzurePricingDownloader()
    
    # Get HW info
    print("Fetching Hardware")
    all_hw = aws_hw.fetch_hardware() + azure_hw.fetch_hardware()
    # Get Price info
    print("Fetching Pricing")
    all_pricing = aws_price.fetch_pricing() + azure_price.fetch_pricing()

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