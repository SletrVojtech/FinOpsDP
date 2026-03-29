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
        rmq.publish(
            queue_name="data_ingestion", 
            message=message.model_dump_json()
        )
    print(message)
    return message

if __name__ == "__main__":
    msg = run_catalog_collector()
    print(json.dumps(msg.payload["pricing_records"][:2], indent=2))