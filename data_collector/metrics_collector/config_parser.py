import yaml
from policy_templates.policy_crafter import CrafterFactory

class ConfigParser:
    def __init__(self, config_path: str = "data_collector/conf/metrics.yml",
                  definitions_path: str = "data_collector/conf/metrics_definitions.yml",
                    safety_overlap_hours: int = 1):
        with open(config_path, 'r') as f:
            self.user_config = yaml.safe_load(f)
            
        with open(definitions_path, 'r') as f:
            self.definitions = yaml.safe_load(f)['metrics_dictionary']
            
        self.safety_overlap_hours = safety_overlap_hours

    def generate_policies(self) -> list:
        policies = []
        
        frequency = self.user_config.get('run_frequency_hours', 1)
        granularity = self.user_config.get('granularity', 'PT5M')
        #granularity = 'PT1H'
        timeframe_hours = frequency + self.safety_overlap_hours
        #timeframe_hours = 1400
        
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
                        unified_name=unified_metric,         # unified name
                        metric=cloud_metric_name, # cloud-specific name
                        agg=agg,
                        timeframe_hours=timeframe_hours,
                        period=granularity
                    )
                
                    policies.append(policy)
                
        return policies
