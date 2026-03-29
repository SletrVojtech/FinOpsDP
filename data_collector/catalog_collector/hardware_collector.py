import boto3
import requests
from typing import Dict, Any, List
from abc import ABC, abstractmethod
from catalog_collector.message import HardwareRecord
import re

class CloudHardwareDownloader(ABC):
    """Abstract class for hardware downloader"""
    @abstractmethod
    def fetch_hardware(self) -> List[Dict[str, Any]]:
        """Returns list of HardwareRecords"""
        pass

class AzureHardwareDownloader(CloudHardwareDownloader):
    """
    Azure hardware downloader from SKU API.
    https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list?view=rest-compute-2025-04-01&tabs=HTTP
    """
    def __init__(self, subscription_id: str, access_token: str):
        self.subscription_id = subscription_id
        self.headers = {"Authorization": f"Bearer {access_token}"}
        # Resource Skus API
        self.base_url = f"https://management.azure.com/subscriptions/{self.subscription_id}/providers/Microsoft.Compute/skus?api-version=2021-07-01"

    def fetch_hardware(self) -> List[Dict[str, Any]]:
        hardware_list = []
        sku_names = set()
        
        url = self.base_url
        # Use Azure API pagination
        while url:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            for item in data.get('value', []):
                if item.get('resourceType') != 'virtualMachines':
                    continue
                
                name = item.get('name')
                if name in sku_names:
                    continue
                sku_names.add(name)
                
                family = item.get('family')
                
                
                # Parse Capabilities
                caps = {cap['name']: cap['value'] for cap in item.get('capabilities', [])}
                
                record = HardwareRecord(
                    cloud="azure",
                    instance_type=name,
                    instance_family=family,
                    vcpu= int(caps.get('vCPUs', 0)),
                    memory_gb= float(caps.get('MemoryGB', 0.0)),
                    baseline_iops= int(caps.get('UncachedDiskIOPS', 0)),
                    baseline_throughput_mbps= int(caps.get('UncachedDiskBytesPerSecond', 0)) / 1024 / 1024 if caps.get('UncachedDiskBytesPerSecond') else None,
                    network_performance= caps.get('MaxNetworkInterfaces')
                )
                hardware_list.append(record)
                
            url = data.get('nextLink')
            
        return hardware_list

class AWSHardwareDownloader(CloudHardwareDownloader):
    """
    AWS hardware downloader from EC2 API.
    https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html
    """
    def __init__(self):
        # Read HW parameters only from 1 region
        self.ec2_client = boto3.client('ec2', region_name='us-east-1')

    def fetch_hardware(self) -> List[Dict[str, Any]]:
        paginator = self.ec2_client.get_paginator('describe_instance_types')
        hardware_list = []
        # Paginate through available instances.
        for page in paginator.paginate():
            for itype in page.get('InstanceTypes', []):
                name = itype['InstanceType']
                family = name.split('.')[0]
                
                vcpu = itype.get('VCpuInfo', {}).get('DefaultVCpus')
                memory_mb = itype.get('MemoryInfo', {}).get('SizeInMiB')
                ebs_info = itype.get('EbsInfo', {}).get('EbsOptimizedInfo', {})
                net_info = itype.get('NetworkInfo', {})
                network_performance = net_info.get('NetworkPerformance')
                match = re.search(r'(\d+)\s*Gigabit', network_performance, re.IGNORECASE)
                perf = 0.0
                if match:
                    perf = float(match.group(1)) * 1000.0
                
                record = HardwareRecord(
                    cloud="aws",
                    instance_type=name,
                    instance_family=family,
                    vcpu=vcpu,
                    memory_gb=memory_mb / 1024.0,
                    baseline_iops=ebs_info.get('BaselineIops'),
                    baseline_throughput_mbps=ebs_info.get('BaselineBandwidthInMbps'),
                    network_performance=str(perf)
                )
                hardware_list.append(record)
        return hardware_list