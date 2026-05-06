"""
Metric Definition Module.

This module defines the MetricDefinition class and a catalog of specific
metric behaviors, including custom transformations for metrics that require
normalization.
"""

from typing import Callable, Dict, Optional


class MetricDefinition:
    """
    Internal transformation class for handling cloud metrics.

    Used to parse and normalize data aggregations that might be unsupported
    directly by cloud provider APIs or require custom logic.
    """
    def __init__(self, fetch_stat: str, transform: Callable[[float, int], float] = lambda v, p: v):
        """
        Initialize the metric definition.

        Args:
            fetch_stat (str): The cloud-provider statistic to fetch (e.g., 'Sum', 'Average').
            transform (Callable[[float, int], float], optional): A function to transform the raw value.
                Receives (value, period_seconds). Defaults to returning the value as-is.
        """
        self.fetch_stat = fetch_stat
        self.transform = transform      


METRICS_CATALOG: Dict[str, MetricDefinition] = {
    "aws_ec2_disk_read_ops_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "aws_ec2_disk_write_ops_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),

    "aws_ec2_disk_read_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "aws_ec2_disk_write_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "azure_vm_disk_read_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "azure_vm_disk_write_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    
    # Returns in bits per second
    "aws_ec2_net_in_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
    "aws_ec2_net_out_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
    "azure_vm_net_in_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
    "azure_vm_net_out_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
    
    "azure_vm_mem_used_avg": MetricDefinition(fetch_stat="avg", transform=lambda v, p: 100.0 - v),
}
    

def get_metric_behavior(metric_name: str) -> MetricDefinition:
    """
    Returns specific metric behavior for unsupported aggregation modes or custom requirements.

    Args:
        metric_name (str): The unified name of the metric.

    Returns:
        MetricDefinition: The definition containing fetch statistics and transformation logic.
    """
    definition = METRICS_CATALOG.get(metric_name)
    if definition:
        return definition
    
    # Fallback: assume the aggregation is the last part of the metric name
    return MetricDefinition(fetch_stat=metric_name.split("_")[-1])
