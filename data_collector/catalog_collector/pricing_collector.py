import requests
from typing import Dict, Any, List
from abc import ABC, abstractmethod
from catalog_collector.message import PricingRecord


class CloudPricingDownloader(ABC):
    """Abstract class for pricing downloader"""

    @abstractmethod
    def fetch_pricing(self) -> List[Dict[str, Any]]:
        """Returns list of PricingRecords"""
        pass

class AzurePricingDownloader(CloudPricingDownloader):
    """
    Azure price API querying.
    https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices
    """
    BASE_URL = "https://prices.azure.com/api/retail/prices"

    def normalize_azure_pricing_os(self, azure_product_name: str) -> str:
        """
        Parse OS name from the Azure product name.
        """
        if not azure_product_name:
            return "Linux"
            
        name_lower = azure_product_name.lower()
        
        if "red hat" in name_lower or "rhel" in name_lower:
            return "RHEL"
        elif "suse" in name_lower or "sles" in name_lower:
            return "SUSE"
        elif "windows" in name_lower:
            return "Windows"
            
        return "Linux"

    def fetch_pricing(self) -> List[Dict[str, Any]]:
        pricing_list = []
        
        # Filter for Virtual machines with Payasyougo pricing
        odata_filter = (
            "serviceName eq 'Virtual Machines' and "
            "priceType eq 'Consumption'"
        )
        url = f"{self.BASE_URL}?$filter={odata_filter}"
        
        print("Fetching Global Azure Pricing")
        while url:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            for item in data.get("Items", []):
                # Ignore spot instances
                if "Spot" in item.get("meterName", ""):
                    continue
                
                # Simplifying the OS
                os_type = self.normalize_azure_pricing_os(item.get("productName"))
                
                record = PricingRecord(
                    cloud= "azure",
                    instance_type= item.get("armSkuName"),
                    region= item.get("armRegionName"),
                    os= os_type,
                    hourly_price_usd= float(item.get("retailPrice", 0.0))
                )
                pricing_list.append(record)
            
            url = data.get("NextPageLink")
            
        return pricing_list

class AWSPricingDownloader(CloudPricingDownloader):
    """
    AWS price API querying
    https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api-fetching-price-list-files-manually.html
    """
    def __init__(self):
        # API for list of all regions
        self.index_url = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/region_index.json"

    def _normalize_aws_pricing_os(self, aws_os_string: str) -> str:
        """
        Unify the oprating system string for AWS.
        """
        if not aws_os_string:
            return "Linux"
            
        os_lower = aws_os_string.lower()
        
        if "red hat" in os_lower or "rhel" in os_lower:
            return "RHEL"
        elif "suse" in os_lower or "sles" in os_lower:
            return "SUSE"
            
        elif "windows" in os_lower:
            return "Windows"
            
        return "Linux"

    def fetch_pricing(self) -> List[Dict[str, Any]]:
        pricing_list = []
        
        # List of regions
        print("Fetching AWS Region Index...")
        regions_data = requests.get(self.index_url).json()
        
        # Iterate over regions
        for region_code, region_info in regions_data.get("regions", {}).items():
            print(f"Downloading AWS pricing for {region_code}...")
            
            # Get the pricing catalog
            regional_json_path = region_info["currentVersionUrl"]
            regional_url = f"https://pricing.us-east-1.amazonaws.com{regional_json_path}"
            
            response = requests.get(regional_url)
            if response.status_code != 200:
                continue
                
            data = response.json()
            products = data.get("products", {})
            terms = data.get("terms", {}).get("OnDemand", {})
            
            # Iterate over the instances
            for sku, product in products.items():
                attrs = product.get("attributes", {})
                
                # Filter out available instances
                if product.get("productFamily") != "Compute Instance" or attrs.get("tenancy") != "Shared" or attrs.get("capacitystatus") != "Used":
                    continue
                
                
                # Get the prices
                sku_terms = terms.get(sku, {})
                for offer in sku_terms.values():
                    for dimension in offer.get("priceDimensions", {}).values():
                        price_usd = float(dimension.get("pricePerUnit", {}).get("USD", 0.0))
                        
                        record = PricingRecord(
                            cloud="aws",
                            instance_type=attrs.get("instanceType"),
                            region=region_code,
                            os=self._normalize_aws_pricing_os(attrs.get("operatingSystem")),
                            hourly_price_usd=price_usd
                        )
                        pricing_list.append(record)
                        
        return pricing_list