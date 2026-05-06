"""
Metrics Message Adapters Module.

This module provides a factory and a set of adapter classes for transforming
raw cloud provider metric data (from AWS CloudWatch or Azure Monitor via Cloud Custodian)
into the unified MetricsPayload format.
"""

from rabbitmq.message import IngestionMessage
from metrics_collector.message import MetricsPayload
from policy_templates.metric_definition import get_metric_behavior

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Type, Optional, Callable
import datetime


class AdapterFactory:
    """
    Registry mapping for metric message adapters.
    """
    _registry: Dict[Tuple[str, str], Type['BaseCloudAdapter']] = {}

    @classmethod
    def register(cls, provider: str, resource_type: str) -> Callable:
        """
        Decorator for registering adapters in the factory.

        Args:
            provider (str): The cloud provider (e.g., 'aws', 'azure').
            resource_type (str): The resource type or 'default'.

        Returns:
            Callable: The decorator function.
        """
        def inner_wrapper(wrapped_class: Type['BaseCloudAdapter']):
            cls._registry[(provider, resource_type)] = wrapped_class
            return wrapped_class
        return inner_wrapper

    @classmethod
    def create(cls, provider: str, res_type: str, raw_resource: Dict[str, Any], **kwargs) -> 'BaseCloudAdapter':
        """
        Returns the best fitting message adapter for the given provider and resource.

        Args:
            provider (str): The cloud provider.
            res_type (str): The resource type string.
            raw_resource (Dict[str, Any]): The raw metric data.
            **kwargs: Additional context for the adapter.

        Returns:
            BaseCloudAdapter: An instance of the appropriate adapter.

        Raises:
            ValueError: If no adapter is found for the provider.
        """
        res_type = res_type.split(".")[-1]
        # Specific adapter
        adapter_class = cls._registry.get((provider, res_type))
        
        # Default cloud adapter
        if not adapter_class:
            adapter_class = cls._registry.get((provider, 'default'))
            
        # Unknown cloud provider.
        if not adapter_class:
            raise ValueError(f"Unknown cloud provider or missing adapter for: {provider}")
            
        return adapter_class(raw_resource, resource_type=res_type, **kwargs)


class BaseCloudAdapter(ABC):
    """
    Base class for adapting cloud provider metrics to the unified format.
    """

    period_dict = {
        'PT5M': 5,
        'PT15M': 15,
        'PT30M': 30,
        'PT1H': 60,
        'PT6H': 360,
        'PT12H': 720,
        'P1D': 1440,
    }
    
    def __init__(self, raw_data: Dict[str, Any], **kwargs):
        """
        Initialize the adapter.

        Args:
            raw_data (Dict[str, Any]): Raw data from the cloud provider.
            **kwargs: Additional metadata (account_id, region_name, etc).
        """
        self.raw_data = raw_data
        self.kwargs = kwargs 

    @abstractmethod
    def get_provider(self) -> str:
        """Returns the provider name."""
        pass

    @abstractmethod
    def get_resource_id(self) -> str:
        """Returns the unique resource identifier."""
        pass

    @abstractmethod
    def get_resource_type(self) -> str:
        """Returns the resource type."""
        pass

    @abstractmethod
    def get_resource_name(self) -> str:
        """Returns the human-readable resource name."""
        pass

    @abstractmethod
    def get_billing_account_id(self) -> str:
        """Returns the billing account or subscription ID."""
        pass

    @abstractmethod
    def get_metric_name(self) -> str:
        """Returns the name of the metric."""
        pass

    @abstractmethod
    def get_region_name(self) -> str:
        """Returns the cloud region name."""
        pass

    @abstractmethod
    def get_tags(self) -> Dict[str, str]:
        """Returns a dictionary of resource tags."""
        pass

    @abstractmethod
    def get_datapoints(self) -> List[Dict[str, Any]]:
        """
        Returns a list of datapoints in {'timestamp': iso8601, 'value': float} format.
        """
        pass

    def get_extras(self) -> Dict[str, Any]:
        """
        Returns a dictionary of special values based on resource type.

        Returns:
            Dict[str, Any]: Extra metadata.
        """
        return {}

    def get_metric_period(self) -> int:
        """
        Returns the metric granularity in minutes.

        Returns:
            int: Period in minutes.
        """
        return self.period_dict.get(self.kwargs.get("granularity", "PT5M"), 5)

    def to_payload(self) -> MetricsPayload:
        """
        Assembles the MetricsPayload object.

        Returns:
            MetricsPayload: The unified metric payload.
        """
        return MetricsPayload(
            provider=self.get_provider(),
            resource_id=self.get_resource_id(),
            resource_type=self.get_resource_type(),
            resource_name=self.get_resource_name(),
            metric_name=self.get_metric_name(),
            metric_period=self.get_metric_period(),
            billing_account_id=self.get_billing_account_id(),
            region_name=self.get_region_name(),
            tags=self.get_tags(),
            datapoints=self.get_datapoints(),
            extras=self.get_extras()
        )


@AdapterFactory.register('azure', 'default')
class AzureAdapter(BaseCloudAdapter):
    """
    Default adapter for Azure resources.
    """
    def get_provider(self) -> str:
        return "azure"

    def get_resource_id(self) -> str:
        return self.raw_data.get("id", "")

    def get_resource_type(self) -> str:
        return self.raw_data.get("type", "unknown")

    def get_resource_name(self) -> str:
        return self.raw_data.get("name", "unknown")

    def get_billing_account_id(self) -> str:
        # Extract Subscription ID from Resource ID
        res_id = self.get_resource_id()
        parts = res_id.split("/")
        if "subscriptions" in parts:
            idx = parts.index("subscriptions")
            if len(parts) > idx + 1:
                return parts[idx + 1]
        return "unknown"

    def get_region_name(self) -> str:
        return self.raw_data.get("location", "unknown")

    def get_tags(self) -> Dict[str, str]:
        return self.raw_data.get("tags", {})

    def _get_raw_metric_data(self) -> Optional[Dict[str, Any]]:
        """Extracts metrics from the c7n:metrics key."""
        metrics_dict = self.raw_data.get("c7n:metrics", {})
        if not metrics_dict:
            return None
        
        # Only one metric at a time. 
        raw_key = list(metrics_dict.keys())[0]
        return metrics_dict[raw_key]

    def get_metric_name(self) -> str:
        policy_name = self.kwargs.get("policy_name", "azure_unknown").split("_", 1)
        if len(policy_name) > 1:
            return policy_name[1]
        return "unknown"

    def get_datapoints(self) -> List[Dict[str, Any]]:
        policy_name = self.kwargs.get("policy_name", "azure_unknown")
        behavior = get_metric_behavior(policy_name)
        data = self._get_raw_metric_data()
        if not data:
            return []

        clean_datapoints = []
        try:
            timeseries_data = data["metrics_data"]["value"][0]["timeseries"][0]["data"]
            period_seconds = self.get_metric_period() * 60

            for point in timeseries_data:
                # Align to period
                ts = (datetime.datetime.fromisoformat(point["time_stamp"]).timestamp() // period_seconds) * period_seconds
                val = point.get("average",
                                point.get("maximum",
                                point.get("minimum",
                                point.get("total",
                                point.get("count", 0.0)))))
                clean_datapoints.append({
                    "timestamp": datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat(),
                    "value": behavior.transform(val, period_seconds)
                })
        except (KeyError, IndexError):
            pass
            
        return clean_datapoints

    def get_extras(self) -> Dict[str, Any]:
        return {}


@AdapterFactory.register('aws', 'default')
class AwsAdapter(BaseCloudAdapter):
    """
    Default adapter for AWS resources.
    """
    def get_provider(self) -> str:
        return "aws"

    def get_resource_id(self) -> str:
        # AWS doesn't have standardized ID name,
        # needs to be implemented per resource-type.
        return self.raw_data.get("InstanceId", self.raw_data.get("Id", "unknown"))

    def get_resource_type(self) -> str:
        return self.kwargs.get("resource_type", "aws_ec2")

    def get_tags(self) -> Dict[str, str]:
        # Parsing list of dictionaries: [{"Key": "x", "Value": "y"}]
        # to a single dictionary
        tags_list = self.raw_data.get("Tags", [])
        return {tag["Key"]: tag["Value"] for tag in tags_list}

    def get_resource_name(self) -> str:
        # Read from tags, otherwise ID
        tags = self.get_tags()
        return tags.get("Name", self.get_resource_id())

    def get_billing_account_id(self) -> str:
        return self.kwargs.get("account_id", "unknown_account")

    def get_region_name(self) -> str:
        return self.kwargs.get("region_name", "unknown")
    
    def _get_raw_metric_data(self) -> List[Dict[str, Any]]:
        """Extract 'c7n.metrics' from raw data."""
        metrics_dict = self.raw_data.get("c7n.metrics", {})
        if not metrics_dict:
            return []
        
        raw_key = list(metrics_dict.keys())[0]
        return metrics_dict[raw_key]
    
    def get_metric_name(self) -> str:
        policy_name = self.kwargs.get("policy_name", "aws_unknown").split("_", 1)
        if len(policy_name) > 1:
            return policy_name[1]
        return "unknown"

    def get_datapoints(self) -> List[Dict[str, Any]]:
        policy_name = self.kwargs.get("policy_name", "aws_unknown")
        behavior = get_metric_behavior(policy_name)
        
        data_list = self._get_raw_metric_data()
        if not data_list:
            return []

        clean_datapoints = []
        period_seconds = self.get_metric_period() * 60
        for point in data_list:
            ts = (datetime.datetime.fromisoformat(str(point["Timestamp"])).timestamp() // period_seconds) * period_seconds
            val = point.get("Average",
                            point.get("Maximum",
                            point.get("Minimum",
                            point.get("Sum",
                            point.get("SampleCount", 0.0)))))
            clean_datapoints.append({
                "timestamp": datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat(),
                "value": behavior.transform(val, period_seconds)
            })
            
        return clean_datapoints

    def get_extras(self) -> Dict[str, Any]:
        return {}


@AdapterFactory.register('aws', 'ec2')
class AwsEc2Adapter(AwsAdapter):
    """Adapter for AWS EC2 instances."""

    def _normalize_aws_os_from_payload(self) -> str:
        """Unify OS type Linux/windows/RedHat/SUSE."""
        vm_properties = self.raw_data
        
        platform_details = vm_properties.get("PlatformDetails", "").lower()
        
        if "red hat" in platform_details or "rhel" in platform_details:
            return "RHEL"
        elif "suse" in platform_details or "sles" in platform_details:
            return "SUSE"
        elif "windows" in platform_details:
            return "Windows"
        elif "linux/unix" in platform_details:
            return "Linux"
            
        platform = vm_properties.get("Platform", "").lower()
        if platform == "windows":
            return "Windows"
            
        return "Linux"

    def get_extras(self) -> Dict[str, Any]:
        extras = super().get_extras()
        extras['normalized_os'] = self._normalize_aws_os_from_payload().lower()
        extras['instance_type'] = self.raw_data.get('InstanceType', 'unknown').lower()
        return extras


@AdapterFactory.register('azure', 'vm')
class AzureVmAdapter(AzureAdapter):
    """Adapter for Azure VM instances."""

    def _normalize_vm_os_from_payload(self) -> str:
        """Unify OS type Linux/windows/RedHat/SUSE."""
        vm_properties = self.raw_data.get("properties", {})
        storage_profile = vm_properties.get("storageProfile", {})
        
        # Try to parse ImageReference
        image_ref = storage_profile.get("imageReference", {})
        publisher = image_ref.get("publisher", "").lower()
        offer = image_ref.get("offer", "").lower()
        
        if "redhat" in publisher or "rhel" in offer:
            return "RHEL"
        elif "suse" in publisher or "sles" in offer:
            return "SUSE"
        
        # Identify by osType
        os_disk = storage_profile.get("osDisk", {})
        os_type = os_disk.get("osType", "").lower()
        
        if os_type == "windows":
            return "Windows"
        elif os_type == "linux":
            return "Linux"
            
        return "Linux"
    
    def get_extras(self) -> Dict[str, Any]:
        extras = super().get_extras()
        extras['normalized_os'] = self._normalize_vm_os_from_payload().lower()
        vm_properties = self.raw_data.get("properties", {})
        hardware_profile = vm_properties.get("hardwareProfile", {})
        extras['instance_type'] = hardware_profile.get('vmSize', 'unknown').lower()
        return extras