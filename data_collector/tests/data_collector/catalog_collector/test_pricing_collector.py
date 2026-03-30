import pytest
from unittest.mock import MagicMock, patch
from catalog_collector.pricing_collector import AzurePricingDownloader, AWSPricingDownloader

def test_azure_pricing_os_normalization():
    downloader = AzurePricingDownloader()
    assert downloader.normalize_azure_pricing_os("Virtual Machines B2s Series Windows") == "Windows"
    assert downloader.normalize_azure_pricing_os("Red Hat Enterprise Linux") == "RHEL"
    assert downloader.normalize_azure_pricing_os("Ubuntu Server") == "Linux"
    assert downloader.normalize_azure_pricing_os("") == "Linux"

@patch('catalog_collector.pricing_collector.requests.get')
def test_azure_pricing_downloader_skips_spot(mock_requests_get):
    # Arrange
    downloader = AzurePricingDownloader()
    
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'Items': [
            {
                'meterName': 'D2s v3',
                'productName': 'Virtual Machines D Series Windows',
                'armSkuName': 'Standard_D2s_v3',
                'armRegionName': 'westeurope',
                'retailPrice': 0.15
            },
            {
                'meterName': 'D2s v3 Spot', # skip spot instances
                'productName': 'Virtual Machines D Series',
                'retailPrice': 0.02
            }
        ],
        'NextPageLink': None
    }
    mock_requests_get.return_value = mock_response

    # Act
    records = downloader.fetch_pricing()

    # Assert
    assert len(records) == 1
    assert records[0].hourly_price_usd == 0.15
    assert records[0].os == "Windows"