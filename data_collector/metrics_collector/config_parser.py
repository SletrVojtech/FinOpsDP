"""
Metrics Config Parser Module.

This module provides the ConfigParser class, which translates high-level metric
collection requirements (defined in metrics.yml) into cloud-specific policies
using templates and definitions.
"""

import yaml
from policy_templates.policy_crafter import CrafterFactory
from typing import List, Tuple, Dict, Any


class ConfigParser:
    """
    Parses metrics configuration and generates collection policies.
    """
    def __init__(self, config_path: str = "conf/metrics.yml",
                  definitions_path: str = "conf/metrics_definitions.yml",
                    safety_overlap_hours: int = 1):
        """
        Initialize the ConfigParser.

        Args:
            config_path (str, optional): Path to the user metrics config. Defaults to "conf/metrics.yml".
            definitions_path (str, optional): Path to the metrics definitions. Defaults to "conf/metrics_definitions.yml".
            safety_overlap_hours (int, optional): Extra hours to fetch to ensure data continuity. Defaults to 1.

        Raises:
            RuntimeError: If configuration files fail to load.
        """
        try:
            with open(config_path, 'r') as f:
                self.user_config = yaml.safe_load(f)
        except (FileNotFoundError, yaml.YAMLError) as e:
            raise RuntimeError(f"Failed to load metrics config from {config_path}: {e}")
            
        try:
            with open(definitions_path, 'r') as f:
                self.definitions = yaml.safe_load(f)['metrics_dictionary']
        except (FileNotFoundError, yaml.YAMLError, KeyError) as e:
            raise RuntimeError(f"Failed to load metrics definitions from {definitions_path}: {e}")
            
        self.safety_overlap_hours = safety_overlap_hours

    def generate_policies(self) -> Tuple[List[Dict[str, Any]], str]:
        """
        Translates user configuration into a list of collection policies.

        Returns:
            Tuple[List[Dict[str, Any]], str]: A tuple containing the list of policies and the granularity string.

        Raises:
            ValueError: If a metric is missing from definitions.
        """
        policies = []
        
        frequency = self.user_config.get('run_frequency_hours', 1)
        granularity = self.user_config.get('granularity', 'PT5M')
        timeframe_hours = frequency + self.safety_overlap_hours
        
        # Iterate over user config
        for measure_block in self.user_config.get('measure', []):
            resource_name = measure_block['resource']
            provider = resource_name.split('.')[0] # 'aws', 'azure'
            
            # Get policy crafter
            crafter = CrafterFactory.get_crafter(resource_name)
            
            for measurement in measure_block.get('measurement', []):
                unified_metric = measurement['metric']
                aggregations = measurement.get('aggregate', ['avg'])
                
                # Translate
                metric_def = self.definitions.get(unified_metric)
                if not metric_def:
                    raise ValueError(f"Metric '{unified_metric}' hasn't been declared.")
                
                cloud_metric_name = metric_def.get(provider)
                if not cloud_metric_name:
                    raise ValueError(f"Metric '{unified_metric}' isn't defined for '{provider}'")

                # Assembling
                for agg in aggregations:
                    policy = crafter.craft(
                        resource=resource_name,
                        unified_name=unified_metric,         # unified metric name
                        metric=cloud_metric_name, # cloud-specific name
                        agg=agg,
                        timeframe_hours=timeframe_hours,
                        period=granularity
                    )
                
                    policies.append(policy)
                
        return policies, granularity
