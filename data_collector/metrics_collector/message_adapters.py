from rabbitmq.message import IngestionMessage
from metrics_collector.message import MetricsPayload
from policy_templates.metric_definition import get_metric_behavior

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Type

import datetime

class AdapterFactory:
    """Registry mapping for adapters"""
    _registry: Dict[Tuple[str, str], Type] = {}

    @classmethod
    def register(cls, provider: str, resource_type: str):
        """Registration of adapters using decorators."""
        def inner_wrapper(wrapped_class):
            cls._registry[(provider, resource_type)] = wrapped_class
            return wrapped_class
        return inner_wrapper

    @classmethod
    def create(cls, provider: str, res_type: str, raw_resource: dict, **kwargs):
        """Returns the best fitting message adapter."""
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
    """Downloaded metrics to RabbitMQ MetricsPayload message adapter class"""
    
    def __init__(self, raw_data: Dict[str, Any], **kwargs):
        """Kwargs for adding data not available in returned values."""
        self.raw_data = raw_data
        self.kwargs = kwargs 

    @abstractmethod
    def get_provider(self) -> str: pass

    @abstractmethod
    def get_resource_id(self) -> str: pass

    @abstractmethod
    def get_resource_type(self) -> str: pass

    @abstractmethod
    def get_resource_name(self) -> str: pass

    @abstractmethod
    def get_billing_account_id(self) -> str: pass

    @abstractmethod
    def get_metric_name(self) -> str: pass

    @abstractmethod
    def get_region_name(self) -> str: pass

    @abstractmethod
    def get_tags(self) -> Dict[str, str]: pass

    @abstractmethod
    def get_datapoints(self) -> List[Dict[str, Any]]:
        """Returns list of {'timestamp': t, 'value': v}"""
        pass

    def get_extras(self) -> Dict[str, Any]:
        """Special values based on resource type"""
        return {}

    def to_payloads(self) -> List[MetricsPayload]:
        """
        Assembles the payload
        """
        return MetricsPayload(
            provider=self.get_provider(),
            resource_id=self.get_resource_id(),
            resource_type=self.get_resource_type(),
            resource_name=self.get_resource_name(),
            metric_name=self.get_metric_name(),
            metric_period = 5,
            billing_account_id=self.get_billing_account_id(),
            region_name=self.get_region_name(),
            tags=self.get_tags(),
            datapoints=self.get_datapoints(),
            extras=self.get_extras()
        )

@AdapterFactory.register('azure', 'default')
class AzureAdapter(BaseCloudAdapter):
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

    def _get_raw_metric_data(self):
        """Extracts metrics """
        metrics_dict = self.raw_data.get("c7n:metrics", {})
        if not metrics_dict:
            return None
        
        # Only one metric at a time. 
        raw_key = list(metrics_dict.keys())[0]
        return metrics_dict[raw_key]

    def get_metric_name(self) -> str:
        policy_name =  self.kwargs.get("policy_name", "azure_unknown").split("_", 1)
        if len(policy_name) > 1:
            return policy_name[1]
        else:
            return "unknown"

    def get_datapoints(self) -> List[Dict[str, Any]]:
        policy_name =  self.kwargs.get("policy_name", "azure_unknown")
        behavior = get_metric_behavior(policy_name)
        data = self._get_raw_metric_data()
        if not data:
            return []

        clean_datapoints = []
        try:
            timeseries_data = data["metrics_data"]["value"][0]["timeseries"][0]["data"]

            policy_aggregation = self.kwargs.get("policy_aggregation", "average")
            for point in timeseries_data:
                time = (datetime.datetime.fromisoformat(point["time_stamp"]).timestamp()//300)*300
                val = point.get("average",
                                        point.get("maximum",
                                        point.get("minimum",
                                        point.get("total",
                                        point.get("count", 0.0)))))
                clean_datapoints.append({
                    "timestamp": datetime.datetime.fromtimestamp(time).isoformat(),
                    "value": behavior.transform(val, 300)
                })
        except (KeyError, IndexError):
            pass
            
        return clean_datapoints

    def get_extras(self) -> Dict[str, Any]:
        return {}



@AdapterFactory.register('aws', 'default')
class AwsAdapter(BaseCloudAdapter):
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
    
    def _get_raw_metric_data(self):
        """Extract 'c7n.metrics' from raw data.
        Only one metric type is present.
        """
        metrics_dict = self.raw_data.get("c7n.metrics", {})
        if not metrics_dict:
            return []
        
        raw_key = list(metrics_dict.keys())[0]
        return metrics_dict[raw_key]
    
    def get_metric_name(self) -> str:
        policy_name =  self.kwargs.get("policy_name", "aws_unknown").split("_", 1)
        if len(policy_name) > 1:
            return policy_name[1]
        else:
            return "unknown"

    def get_datapoints(self) -> List[Dict[str, Any]]:
        policy_name =  self.kwargs.get("policy_name", "aws_unknown")
        behavior = get_metric_behavior(policy_name)
        
        data_list = self._get_raw_metric_data()
        if not data_list:
            return []

        clean_datapoints = []
        for point in data_list:
            time = (datetime.datetime.fromisoformat(str(point["Timestamp"])).timestamp()//300)*300
            val = point.get("Average",
                                        point.get("Maximum",
                                        point.get("Minimum",
                                        point.get("Sum",
                                        point.get("SampleCount", 0.0)))))
            clean_datapoints.append({
                "timestamp": datetime.datetime.fromtimestamp(time).isoformat(),
                "value": behavior.transform(val, 300)
            })
            
        return clean_datapoints

    def get_extras(self) -> Dict[str, Any]:
        return {}

@AdapterFactory.register('aws', 'ec2')
class AwsEc2Adapter(AwsAdapter):
    """Class for parsing extra metadata from EC2 instances."""

    def _normalize_aws_os_from_payload(self) -> str:
        """
            Unify OS type Linux/windows/RedHat/SUSE
        """
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
            
        # Fallback
        return "Linux"

    def get_extras(self) -> dict:
        extras = super().get_extras()
        extras['normalized_os'] = self._normalize_aws_os_from_payload()
        return extras

@AdapterFactory.register('azure', 'vm')
class AzureVmAdapter(AzureAdapter):
    """Class for parsing extra metadata from VM instances."""

    def _normalize_vm_os_from_payload(self) -> str:
        """
        Unify OS type Linux/windows/RedHat/SUSE
        """
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
            
        # Fallback for custom images that should have base Linux pricing
        return "Linux"
    
    def get_extras(self) -> dict:
        extras = super().get_extras()
        extras['normalized_os'] = self._normalize_vm_os_from_payload()
        return extras