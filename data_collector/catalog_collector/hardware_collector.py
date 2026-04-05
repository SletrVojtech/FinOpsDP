import boto3
import requests
from typing import Dict, Any, List, Optional
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
        self.base_url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/providers/Microsoft.Compute/skus?api-version=2021-07-01"
        )
 

    def fetch_hardware(self) -> List[Dict[str, Any]]:
        hardware_list = []
        sku_names: set = set()

        url = self.base_url
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

                family = item.get('family', '').lower()

                # Parse Capabilities into a flat dict
                caps = {cap['name']: cap['value'] for cap in item.get('capabilities', [])}

                # Architecture
                arch_raw = caps.get('Architecture', 'x64').lower()
                architecture = 'arm64' if 'arm' in arch_raw else 'x86_64'

                # GPU
                gpu_count = int(caps.get('GPUs', 0))
                is_gpu = gpu_count > 0

                # Premium Storage (low-latency IO controller)
                supports_premium = caps.get('PremiumIO', 'False').lower() == 'true'

                # Confidential Computing
                is_confidential = (
                    caps.get('ConfidentialComputingType') is not None
                    or 'dc' in family
                    or 'ec' in family
                )

                # Local Storage
                max_resource_volume_mb = int(caps.get('MaxResourceVolumeMB', 0))
                has_local_storage = max_resource_volume_mb > 0

                # Network throughput
                net_perf: Optional[str] = None
                net_perf = int(caps.get('vCPUs', 0)) * 500 if caps.get('vCPUs') else None
                # Storage
                uncached_iops = int(caps.get('UncachedDiskIOPS', 0))
                uncached_bps = caps.get('UncachedDiskBytesPerSecond')
                throughput_mbps = (
                    int(uncached_bps) / 1024 / 1024 if uncached_bps else None
                )

                record = HardwareRecord(
                    cloud="azure",
                    instance_type=name,
                    instance_family=family,
                    vcpu=int(caps.get('vCPUs', 0)),
                    memory_gb=float(caps.get('MemoryGB', 0.0)),
                    baseline_iops=uncached_iops or None,
                    baseline_throughput_mbps=throughput_mbps,
                    network_performance=str(net_perf),
                    architecture=architecture,
                    is_gpu=is_gpu,
                    is_confidential=is_confidential,
                    has_local_storage=has_local_storage,
                    supports_premium_storage=supports_premium,
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
        # Read HW parameters only from 1 region, specs are global
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
                network_performance_str = net_info.get('NetworkPerformance', '')
                match = re.search(r'(\d+(?:\.\d+)?)\s*Gigabit', network_performance_str, re.IGNORECASE)
                net_mbps: Optional[float] = None
                if match:
                    net_mbps = float(match.group(1)) * 1000.0

                # Architecture
                arch_list = (
                    itype.get('ProcessorInfo', {})
                         .get('SupportedArchitectures', ['x86_64'])
                )
                architecture = 'arm64' if 'arm64' in arch_list else 'x86_64'

                # GPU
                gpus = itype.get('GpuInfo', {}).get('Gpus', [])
                is_gpu = len(gpus) > 0

                # Premium Storage
                ebs_support = itype.get('EbsInfo', {}).get('EbsOptimizedSupport', 'unsupported')
                supports_premium = ebs_support in ('default', 'supported')

                # Confidential Computing
                enclave_support = itype.get('NitroEnclavesSupport', 'unsupported')
                is_confidential = enclave_support == 'supported'

                # Local Storage
                has_local_storage = itype.get('InstanceStorageSupported', False)

                record = HardwareRecord(
                    cloud="aws",
                    instance_type=name,
                    instance_family=family,
                    vcpu=vcpu,
                    memory_gb=memory_mb / 1024.0,
                    baseline_iops=ebs_info.get('BaselineIops'),
                    baseline_throughput_mbps=ebs_info.get('BaselineBandwidthInMbps'),
                    network_performance=str(net_mbps) if net_mbps is not None else None,
                    architecture=architecture,
                    is_gpu=is_gpu,
                    is_confidential=is_confidential,
                    has_local_storage=has_local_storage,
                    supports_premium_storage=supports_premium,
                )
                hardware_list.append(record)

        return hardware_list