import pytest
from policy_templates.metric_definition import get_metric_behavior, MetricDefinition

def test_get_metric_behavior_known_catalog_item():
    # Arrange & Act: Bytes -> bits/s
    behavior = get_metric_behavior("aws_ec2_net_in_avg")
    
    # Assert
    assert behavior.fetch_stat == "sum" # net_in needs sum query
    
    assert behavior.transform(v=100, p=5) == (100 * 8) / 5
    
    # Test for division by 0 (p > 0 else 0)
    assert behavior.transform(v=100, p=0) == 0

def test_get_metric_behavior_disk_ops():
    # Arrange & Act: Disk operations are averaged from sum (v / p)
    behavior = get_metric_behavior("aws_ec2_disk_read_ops_avg")
    
    # Assert
    assert behavior.fetch_stat == "sum"
    assert behavior.transform(v=300, p=300) == 1.0 # 300 ops in 300s = 1 ops/s
    assert behavior.transform(v=50, p=0) == 0

def test_get_metric_behavior_unknown_fallback():
    # Fallback for unspecified policies - keep the same aggregations and no transform
    behavior = get_metric_behavior("aws_ec2_cpu_usage_max")
    
    # Assert
    assert behavior.fetch_stat == "max"
    assert behavior.transform(v=99.9, p=300) == 99.9