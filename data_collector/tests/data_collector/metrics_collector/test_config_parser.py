import pytest
import yaml
from unittest.mock import patch, mock_open
from metrics_collector.config_parser import ConfigParser

# Mocked configs for testing
MOCK_METRICS_YML = """
run_frequency_hours: 1
granularity: "PT5M"
measure:
  - resource: aws.ec2
    measurement:
      - metric: cpu_usage
        aggregate: ["avg"]
"""

MOCK_DEF_YML = """
metrics_dictionary:
  cpu_usage:
    aws: "CPUUtilization"
    azure: "Percentage CPU"
"""

@patch("builtins.open", new_callable=mock_open)
def test_config_parser_generates_valid_aws_policy(mock_file):
    # Setup mock_open to return different contents based on file name
    handlers = {
        "conf/metrics.yml": mock_open(read_data=MOCK_METRICS_YML).return_value,
        "conf/metrics_definitions.yml": mock_open(read_data=MOCK_DEF_YML).return_value
    }
    mock_file.side_effect = lambda filename, *args, **kwargs: handlers.get(filename, mock_open(read_data="").return_value)

    # Act
    parser = ConfigParser(config_path="conf/metrics.yml", definitions_path="conf/metrics_definitions.yml")
    policies = parser.generate_policies()

    # Assert
    assert len(policies) == 1
    policy = policies[0]
    
    assert policy["name"] == "aws_ec2_cpu_usage_avg"
    assert policy["resource"] == "aws.ec2"
    assert len(policy["filters"]) == 1
    
    metrics_filter = policy["filters"][0]
    assert metrics_filter["type"] == "metrics"
    assert metrics_filter["name"] == "CPUUtilization"
    assert metrics_filter["statistics"] == "Average"