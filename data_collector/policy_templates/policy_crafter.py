"""
Policy Crafter Module.

This module provides the PolicyCrafter abstraction and provider-specific
implementations (AWS, Azure) for programmatically generating Cloud Custodian
policies for metric collection.
"""

from abc import ABC, abstractmethod
import string
from typing import Dict, Any, Optional, List
from policy_templates.metric_definition import get_metric_behavior


class PolicyCrafter(ABC):
    """
    Abstract base class for cloud-provider-specific policy crafters.
    """

    def craft_name(self, resource: str, metric: str, aggregation: str = 'avg') -> str:
        """
        Generates a standardized policy name from resource and metric details.

        Args:
            resource (str): The cloud resource type (e.g., 'aws.ec2').
            metric (str): The metric name.
            aggregation (str, optional): The aggregation mode. Defaults to 'avg'.

        Returns:
            str: A universal policy name.
        """
        # Based on https://www.digitalocean.com/community/tutorials/python-remove-spaces-from-string
        s = resource + '_' + metric + '_' + aggregation
        replacements = str.maketrans(
            {" ": "_", ".": "_", "-": "_", "/": "_", "\\": "_"}
            | {ord(c): None for c in string.whitespace})
        return s.translate(replacements)
            
    @abstractmethod
    def craft(self, resource: str, unified_name: str, metric: str, 
              timeframe_hours: int, period: str = 'PT5M', agg: str = 'avg') -> Dict[str, Any]:
        """
        Crafts a Cloud Custodian policy dictionary.

        Args:
            resource (str): The cloud resource type.
            unified_name (str): The unified metric name.
            metric (str): The cloud-provider-specific metric name.
            timeframe_hours (int): The history window in hours.
            period (str, optional): The metric granularity. Defaults to 'PT5M'.
            agg (str, optional): The requested aggregation. Defaults to 'avg'.

        Returns:
            Dict[str, Any]: A complete Cloud Custodian policy dictionary.
        """
        pass


class AWSPolicyCrafter(PolicyCrafter):
    """
    Policy crafter for AWS (CloudWatch).
    """
    AGGREGATION_MAP = {
        'avg': 'Average',
        'max': 'Maximum',
        'min': 'Minimum',
        'sum': 'Sum',
        'count': 'SampleCount'
    }

    def _get_period(self, period: str) -> int:
        """
        Translates period string to seconds.

        Args:
            period (str): period (e.g., 'PT5M').

        Returns:
            int: Period in seconds. Defaults to 300 (5 minutes).
        """
        period_dict = {
            'PT5M': 300,
            'PT15M': 900,
            'PT30M': 1800,
            'PT1H': 3600,
            'PT6H': 21600,
            'PT12H': 43200,
            'P1D': 86400,
        }
        return period_dict.get(period, 300)

    def craft(self, resource: str, unified_name: str, metric: str, 
              timeframe_hours: int, period: str = 'PT5M', agg: str = 'avg') -> Dict[str, Any]:
        """
        Crafts an AWS Cloud Custodian policy.

        Args:
            resource (str): The AWS resource type (e.g., 'aws.ec2').
            unified_name (str): The unified metric name.
            metric (str): The AWS CloudWatch metric name.
            timeframe_hours (int): The history window in hours.
            period (str, optional): The metric granularity. Defaults to 'PT5M'.
            agg (str, optional): The requested aggregation. Defaults to 'avg'.

        Returns:
            Dict[str, Any]: The AWS-specific policy dictionary.
        """
        days_back = timeframe_hours / 24.0
        name = self.craft_name(resource, unified_name, agg)
        
        # Check if the metric requires a specific fetch statistic
        aws_stat_key = get_metric_behavior(name).fetch_stat
        aws_stat = self.AGGREGATION_MAP.get(aws_stat_key.lower(), 'Average')

        policy_data = {
            'name': name, 
            'resource': resource, 
            'filters': [{
                'type': 'metrics', 
                'name': metric, 
                'days': days_back, 
                'period': self._get_period(period), 
                'value': 0,
                'missing-value': 0,
                'statistics': aws_stat,
                'op': 'ge'
            }]
        }
        return policy_data


class AzurePolicyCrafter(PolicyCrafter):
    """
    Policy crafter for Azure (Azure Monitor).
    """
    AGGREGATION_MAP = {
        'avg': 'average',
        'max': 'maximum',
        'min': 'minimum',
        'sum': 'total',
        'count': 'count'
    }

    def craft(self, resource: str, unified_name: str, metric: str, 
              timeframe_hours: int, period: str = 'PT5M', agg: str = 'avg') -> Dict[str, Any]:
        """
        Crafts an Azure Cloud Custodian policy.

        Args:
            resource (str): The Azure resource type (e.g., 'azure.vm').
            unified_name (str): The unified metric name.
            metric (str): The Azure Monitor metric name.
            timeframe_hours (int): The history window in hours.
            period (str, optional): The metric granularity. Defaults to 'PT5M'.
            agg (str, optional): The requested aggregation. Defaults to 'avg'.

        Returns:
            Dict[str, Any]: The Azure-specific policy dictionary.
        """
        name = self.craft_name(resource, unified_name, agg)
        
        # Check if the metric requires a specific fetch statistic
        azure_stat_key = get_metric_behavior(name).fetch_stat
        azure_stat = self.AGGREGATION_MAP.get(azure_stat_key.lower(), 'average')
        
        policy_data = {
            'name': name,
            'resource': resource,
            'filters': [{
                'type': 'metric',
                'metric': metric, 
                'aggregation': azure_stat, 
                'op': 'ge', 
                'threshold': 0, 
                'timeframe': timeframe_hours, 
                'interval': period,
                'no_data_action': 'to_zero'
            }]
        }
        return policy_data


class CrafterFactory:
    """
    Factory for retrieving the appropriate PolicyCrafter for a given resource.
    """
    _mapping: Dict[str, PolicyCrafter] = {
        'aws': AWSPolicyCrafter(),
        'azure': AzurePolicyCrafter()
    }

    @staticmethod
    def get_crafter(resource_name: str) -> PolicyCrafter:
        """
        Returns the appropriate PolicyCrafter based on the resource name prefix.

        Args:
            resource_name (str): The resource name (e.g., 'aws.ec2').

        Returns:
            PolicyCrafter: The provider-specific crafter instance.

        Raises:
            ValueError: If the provider prefix is not supported.
        """
        # Get the resource prefix for provider mapping (e.g., 'aws' from 'aws.ec2')
        prefix = resource_name.split('.')[0]
        crafter = CrafterFactory._mapping.get(prefix)
        
        if not crafter:
            raise ValueError(f"Provider '{prefix}' is not supported.")
        return crafter