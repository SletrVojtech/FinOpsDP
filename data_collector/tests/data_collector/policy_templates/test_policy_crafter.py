import pytest
from policy_templates.policy_crafter import (
    CrafterFactory,
    AWSPolicyCrafter,
    AzurePolicyCrafter
)

def test_crafter_factory():
    # Check returned instance
    assert isinstance(CrafterFactory.get_crafter('aws.ec2'), AWSPolicyCrafter)
    assert isinstance(CrafterFactory.get_crafter('aws.rds'), AWSPolicyCrafter)
    assert isinstance(CrafterFactory.get_crafter('azure.vm'), AzurePolicyCrafter)
    
    # Expect ValueError for unknown provider
    with pytest.raises(ValueError) as exc_info:
        CrafterFactory.get_crafter('gcp.compute')
    assert "Provider 'gcp' isn't supported" in str(exc_info.value)

def test_craft_name_cleaning():
    # Removes all whitespace and special characters are parsed as '_'
    crafter = AWSPolicyCrafter()
    
    clean_name = crafter.craft_name('aws.ec2', 'CPU Usage', 'avg')
    assert clean_name == "aws_ec2_CPUUsage_avg"

def test_aws_policy_crafter_standard():
    crafter = AWSPolicyCrafter()
    
    # Create policy
    policy = crafter.craft(
        resource="aws.ec2", 
        unified_name="cpu_usage", 
        metric="CPUUtilization", 
        timeframe_hours=24, 
        period="PT1H", # 1 hour 
        agg="max"
    )
    
    assert policy['name'] == "aws_ec2_cpu_usage_max"
    assert policy['resource'] == "aws.ec2"
    
    # Check parameters for CloudCustodian policy
    filters = policy['filters'][0]
    assert filters['type'] == "metrics"
    assert filters['name'] == "CPUUtilization"
    assert filters['days'] == 1.0 # 24 hours / 24.0
    assert filters['period'] == 3600 # seconds
    assert filters['statistics'] == "Maximum" # mapped from "max" using AGGREGATION_MAP

def test_aws_policy_crafter_with_catalog_override():
    # Test catalog - net_in_avg needs sum query and then transformation.
    crafter = AWSPolicyCrafter()
    
    policy = crafter.craft(
        resource="aws.ec2", 
        unified_name="net_in", 
        metric="NetworkIn", 
        timeframe_hours=12, 
        period="PT5M", 
        agg="avg"
    )
    
    # Average -> Sum
    filters = policy['filters'][0]
    assert filters['statistics'] == "Sum"
    assert filters['days'] == 0.5

def test_azure_policy_crafter_standard():
    crafter = AzurePolicyCrafter()
    
    policy = crafter.craft(
        resource="azure.vm", 
        unified_name="cpu_usage", 
        metric="Percentage CPU", 
        timeframe_hours=48, 
        period="PT15M", 
        agg="avg"
    )
    
    assert policy['name'] == "azure_vm_cpu_usage_avg"
    assert policy['resource'] == "azure.vm"
    
    # Azure has specific filter format
    filters = policy['filters'][0]
    assert filters['type'] == "metric" # AWS = 'metrics', Azure = 'metric'
    assert filters['metric'] == "Percentage CPU"
    assert filters['timeframe'] == 48 # hours
    assert filters['interval'] == "PT15M"
    assert filters['aggregation'] == "average" # mapped from "avg"