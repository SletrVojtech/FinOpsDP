import pytest
from metrics_collector.message_adapters import AdapterFactory

def test_azure_vm_adapter_real_data():
    # Real shortened data received from CloudCustodian with anonymized subscription
    raw_azure_vm = {
        "id": "/subscriptions/9e97b1e3-0905-4d1f-b923-d050f30d1/resourceGroups/DP_OWN/providers/Microsoft.Compute/virtualMachines/vmNorw",
        "name": "vmNorw",
        "type": "Microsoft.Compute/virtualMachines",
        "location": "swedencentral",
        "tags": {"main": "true"},
        "properties": {
            "hardwareProfile": {"vmSize": "Standard_D4s_v3"},
            "storageProfile": {
                "osDisk": {"osType": "Linux"}
            }
        },
        "resourceGroup": "DP_OWN",
        "c7n:metrics": {
            "Percentage CPU, average, 3.0, 0:05:00, None": {
                "metrics_data": {
                    "value": [{
                        "timeseries": [{
                            "data": [
                                {"time_stamp": "2026-02-25T19:25:00.000Z", "average": 0.14},
                                {"time_stamp": "2026-02-25T19:30:00.000Z", "average": 0.145}
                            ]
                        }]
                    }]
                }
            }
        }
    }
    
    # Act
    adapter = AdapterFactory.create(
        provider="azure", 
        res_type="azure.vm", 
        raw_resource=raw_azure_vm, 
        policy_name="azure_vm_cpu_usage_avg"
    )
    payload = adapter.to_payloads()

    # Assert
    assert payload.provider == "azure"
    assert payload.resource_id == "/subscriptions/9e97b1e3-0905-4d1f-b923-d050f30d1/resourceGroups/DP_OWN/providers/Microsoft.Compute/virtualMachines/vmNorw"
    assert payload.resource_name == "vmNorw"
    assert payload.region_name == "swedencentral"
    assert payload.tags["main"] == "true"
    
    # Check Extras for VM instance
    assert payload.extras.get("normalized_os") == "Linux".lower()
    assert payload.extras.get("instance_type") == "Standard_D4s_v3".lower()


    # Check datapoints
    assert len(payload.datapoints) == 2
    assert payload.datapoints[0]["value"] == 0.14
    assert payload.datapoints[0]["timestamp"] == "2026-02-25T19:25:00+00:00"


def test_aws_ec2_adapter_real_data():
    # Real shortened data returned by CloudCustodian
    raw_aws_ec2 = {
        "Architecture": "x86_64",
        "PlatformDetails": "Linux/UNIX",
        "InstanceId": "i-0cb80bfbb88f65214",
        "InstanceType": "t2.nano",
        "Tags": [
            {"Key": "main", "Value": "true"},
            {"Key": "Name", "Value": "DPins"}
        ],
        "c7n.metrics": {
            "AWS/EC2.CPUUtilization.Average.0.02": [
                {
                    "Timestamp": "2026-02-24T13:25:00+01:00",
                    "Average": 3.206656126639699,
                    "Unit": "Percent"
                },
                {
                    "Timestamp": "2026-02-24T13:30:00+01:00",
                    "Average": 3.203153786412203,
                    "Unit": "Percent"
                }
            ]
        }
    }

    # Act
    adapter = AdapterFactory.create(
        provider="aws", 
        res_type="aws.ec2", 
        raw_resource=raw_aws_ec2, 
        policy_name="aws_ec2_cpu_usage_avg",
        account_id="554882957058",
        region_name="us-east-1"
    )
    payload = adapter.to_payloads()

    # Assert
    assert payload.provider == "aws"
    assert payload.resource_id == "i-0cb80bfbb88f65214"
    
    # Parse tags
    assert payload.resource_name == "DPins"
    assert payload.tags["main"] == "true"
    
    # Check kwargs
    assert payload.billing_account_id == "554882957058"
    assert payload.region_name == "us-east-1"
    
    # Check instance name for aws.EC2 instances
    assert payload.extras.get("normalized_os") == "Linux".lower()

    # Loaded datapoints
    assert len(payload.datapoints) == 2
    assert payload.datapoints[0]["value"] == 3.206656126639699