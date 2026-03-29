from typing import Callable

class MetricDefinition:
    """
    Internal transformation class to parse data aggregations unsupported by cloud APIs
    """
    def __init__(self, fetch_stat: str, transform: Callable[[float, int], float] = lambda v, p: v):
        self.fetch_stat = fetch_stat
        self.transform = transform      

METRICS_CATALOG = {
    "aws_ec2_disk_read_ops_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "aws_ec2_disk_write_ops_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),

    "aws_ec2_disk_read_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "aws_ec2_disk_write_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "azure_vm_disk_read_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    "azure_vm_disk_write_bytes_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: v / p if p > 0 else 0),
    # returns in bit per second
    "aws_ec2_net_in_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
    "aws_ec2_net_out_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
    "azure_vm_net_in_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
    "azure_vm_net_out_avg": MetricDefinition(fetch_stat="sum", transform=lambda v, p: (v * 8) / p if p > 0 else 0),
}

def get_metric_behavior(metric_name: str) -> MetricDefinition:
    """Returns specific metric behaviour for unsuported aggregation modes"""

    definition = METRICS_CATALOG.get(metric_name)
    if definition:
        return definition
    return MetricDefinition(fetch_stat=metric_name.split("_")[-1])
