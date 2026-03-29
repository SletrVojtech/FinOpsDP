from abc import ABC, abstractmethod
import string
from policy_templates.metric_definition import get_metric_behavior

class PolicyCrafter(ABC):
    """Abstract class for supported providers"""

    def craft_name(self, resource, metric, aggregation='avg'):
        # Based on https://www.digitalocean.com/community/tutorials/python-remove-spaces-from-string
        s = resource + '_' + metric + '_' + aggregation
        replacements = str.maketrans(
            {" ": "_", ".": "_", "-": "_", "/": "_", "\\": "_"}
            | {ord(c): None for c in string.whitespace})
        return s.translate(replacements)
            
    @abstractmethod
    def craft(self,resource: str, unified_name:str, metric: str,timeframe_hours: int, period: str = 'PT5M', agg='avg'):
        pass

class AWSPolicyCrafter(PolicyCrafter):
    AGGREGATION_MAP = {
        'avg': 'Average',
        'max': 'Maximum',
        'min': 'Minimum',
        'sum': 'Sum',
        'count': 'SampleCount'
    }

    def _get_period(self,period: str):
        """
        Based on allowed granularity for Azure policies in c7n_azure.filters.schema
        Enumerates to seconds, default is 5 minutes.
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


    def craft(self,resource: str, unified_name:str, metric: str,timeframe_hours: int, period: str = 'PT5M', agg='avg'):
        days_back = timeframe_hours / 24.0
        name = self.craft_name(resource,unified_name, agg)
        aws_stat = get_metric_behavior(name).fetch_stat
        aws_stat = self.AGGREGATION_MAP.get(aws_stat.lower(), 'Average')

        POLICY_DATA = {
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
        return POLICY_DATA

class AzurePolicyCrafter(PolicyCrafter):
    AGGREGATION_MAP = {
        'avg': 'average',
        'max': 'maximum',
        'min': 'minimum',
        'sum': 'total',
        'count': 'count'
    }

    def craft(self,resource: str, unified_name:str, metric: str,timeframe_hours: int, period: str = 'PT5M', agg='avg'):
        name = self.craft_name(resource,unified_name, agg)
        azure_stat = get_metric_behavior(name).fetch_stat
        azure_stat = self.AGGREGATION_MAP.get(azure_stat.lower(), 'average')
        POLICY_DATA = {
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
                },]
        }
        return POLICY_DATA

class CrafterFactory:
    _mapping = {
        'aws': AWSPolicyCrafter(),
        'azure': AzurePolicyCrafter()
    }

    @staticmethod
    def get_crafter(resource_name: str) -> PolicyCrafter:
        # Get the resource prefix for provider mapping
        prefix = resource_name.split('.')[0]
        crafter = CrafterFactory._mapping.get(prefix)
        
        if not crafter:
            raise ValueError(f"Provider '{prefix}' isn't supported..")
        return crafter