"""
Metrics Collection Orchestrator.

This script uses Cloud Custodian in-memory execution to collect metrics from
AWS and Azure accounts and publishes them to RabbitMQ.
"""

import time
import logging
from botocore.exceptions import ClientError
from c7n.policy import PolicyCollection
from c7n.config import Config
from c7n.loader import PolicyLoader
from c7n_org.utils import environ, account_tags
from c7n_org.cli import get_session, _get_env_creds
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from c7n_org.cli import init, resolve_regions, accounts_iterator
from policy_templates.policy_crafter import CrafterFactory
from policy import InMemoryPullMode
from rabbitmq.connector import RabbitMQClient
from rabbitmq.message import IngestionMessage
from metrics_collector.message_adapters import AdapterFactory
from metrics_collector.config_parser import ConfigParser
from registry import register_collector
from typing import Dict, Any

log = logging.getLogger('metrics_collector')


class CustodianAccountWorker:
    """
    Handles the execution of Cloud Custodian policies for a specific account and region.
    """
    def __init__(self, account, region, policy_data, output_dir, granularity, debug=False):
        """
        Initialize the worker.

        Args:
            account (dict): Account configuration.
            region (str): Cloud region.
            policy_data (dict): Policy definitions.
            output_dir (str): Directory for logs/output.
            granularity (str): Metrics granularity (e.g., PT5M).
            debug (bool): Enable debug logging.
        """
        self.account = account
        self.region = region
        self.policy_data = policy_data
        self.output_dir = output_dir
        self.granularity = granularity
        self.debug = debug
        self.success = False
        self.policy_counts = {}
        self.provider = account.get('provider')

    def run(self) -> tuple:
        """
        Main execution flow for the account/region.

        Returns:
            tuple: (policy_counts, success_flag)
        """
        options = self._setup_options()
        env_vars = self._get_env_vars()

        # Isolated environment variables for the cloud provider calls
        with environ(**env_vars):
            loader = PolicyLoader(options)
            policy_provider = f"*{self.provider}*"
            
            # Load and filter policies for current provider
            collection = loader.load_data(self.policy_data, "in-memory").filter(policy_patterns=[policy_provider])
            
            with RabbitMQClient() as mq_client:
                for policy in collection:
                    try:
                        self._run_policy(policy, mq_client)
                        self.success = True
                    except ClientError as e:
                        self.success = False or self.success
                        if e.response['Error']['Code'] == 'AccessDenied':
                            log.warning('Access denied api:%s policy:%s account:%s region:%s',
                                        e.operation_name, policy.name, self.account['name'], self.region)
                            continue
                        log.error("Exception running policy:%s account:%s error:%s",
                                 policy.name, self.account['name'], e)
                    except Exception as e:
                        self.success = False
                        log.error("Exception running policy:%s account:%s error:%s",
                                 policy.name, self.account['name'], e)
                        if self.debug:
                            raise
        
        return self.policy_counts, self.success

    def _setup_options(self) -> Config:
        """
        Initializes Custodian configuration options for the current execution.

        Returns:
            Config: A Cloud Custodian configuration object containing region and output settings.
        """
        options = Config.empty(
            region=self.region,
            output_dir=self.output_dir,
            metrics_enabled=False,
        )
        if self.account.get('role'):
            if isinstance(self.account['role'], str):
                options['assume_role'] = self.account['role']
                options['external_id'] = self.account.get('external_id')
        elif self.account.get('profile'):
            options['profile'] = self.account['profile']
        return options

    def _get_env_vars(self) -> Dict[str, str]:
        """
        Prepares environment variables (credentials and tags) for the cloud session.

        Returns:
            Dict[str, str]: A dictionary of environment variables to be used during policy execution.
        """
        env_vars = account_tags(self.account)
        if self.account.get('role') and not isinstance(self.account['role'], str):
            env_vars.update(
                _get_env_creds(self.account, get_session(self.account, 'custodian', self.region), self.region))
        return env_vars

    def _run_policy(self, policy: Any, mq_client: RabbitMQClient):
        """
        Executes a single Cloud Custodian policy and handles result ingestion.

        Args:
            policy (Any): The Cloud Custodian policy object to execute.
            mq_client (RabbitMQClient): An active RabbitMQ client for publishing findings.
        """
        # Force in-memory-pull mode
        if policy.data.get('mode', {}).get('type', 'pull') == 'pull':
            policy.data['mode'] = {'type': 'in-memory-pull'}
        
        policy.data['regions'] = [self.region]
        policy.expand_variables(policy.get_variables())
        policy.conditions.env_vars['account'] = self.account
        policy.expand_variables(policy.get_variables(self.account.get('vars', {})))

        log.debug("Running policy:%s account:%s region:%s", 
                  policy.name, self.account['name'], self.region)
        
        st = time.time()
        resources = policy()
        self.policy_counts[policy.name] = len(resources) if resources else 0
        
        if not resources:
            return

        # Adapt and publish results
        for raw_resource in resources:
            self._publish_resource(policy, raw_resource, mq_client)

        log.info("Ran account:%s region:%s policy:%s matched:%d time:%0.2f",
                 self.account['name'], self.region, policy.name, len(resources), time.time() - st)

    def _publish_resource(self, policy: Any, raw_resource: Dict[str, Any], mq_client: RabbitMQClient):
        """
        Adapts a single resource to the internal format and publishes it to RabbitMQ.

        Args:
            policy (Any): The Cloud Custodian policy that matched the resource.
            raw_resource (Dict[str, Any]): The raw resource data including metrics.
            mq_client (RabbitMQClient): An active RabbitMQ client for publishing the message.
        """
        kwargs = {
            'policy_name': policy.name,
            'granularity': self.granularity
        }
        if self.provider == 'aws':
            kwargs['account_id'] = self.account.get('account_id', 'unknown')
            kwargs['region_name'] = self.region

        adapter = AdapterFactory.create(
            provider=self.provider, 
            res_type=policy.resource_type, 
            raw_resource=raw_resource, 
            **kwargs
        )
        
        metrics_payload = adapter.to_payload()
        msg = IngestionMessage(
            source_module="custodian",
            payload=metrics_payload.model_dump()
        )
        mq_client.publish(
            queue_name="data_ingestion", 
            message=msg.model_dump_json()
        )


def run_account_in_memory(account, region, policy_data, output_dir, granularity, debug=False):
    """
    Worker function for the concurrent executor. 

    Args:
        account (dict): Account configuration.
        region (str): Cloud region.
        policy_data (dict): Policy definitions.
        output_dir (str): Directory for logs/output.
        granularity (str): Metrics granularity.
        debug (bool): Enable debug logging.

    Returns:
        tuple: (policy_counts, success_flag)
    """
    worker = CustodianAccountWorker(account, region, policy_data, output_dir, granularity, debug)
    return worker.run()


@register_collector("metrics", help_text="Download metrics using Custodian and send to RMQ")
def run_metrics_collector():
    """
    Main entry point for metrics collection across all accounts and regions.
    """
    try:
        parser = ConfigParser()
        generated_policies, granularity = parser.generate_policies()
        POLICY_DATA = {"policies": generated_policies}
    except Exception as e:
        log.error(f"Error loading policies: {e}")
        raise ValueError(f"Failed to initialize metrics collector: {e}")

    # Load account configurations
    accounts_config, _, _ = init(
        config='.conf/accounts.yml',
        use=None,
        debug=False,
        verbose=False,
        accounts=None, tags=None, policies=None
    )

    azure_config, _, _ = init(
        config='.conf/subscriptions.yml',
        use=None,
        debug=False,
        verbose=False,
        accounts=None, tags=None, policies=None
    )

    accounts_config["subscriptions"] = azure_config.get("subscriptions", ())
    

    worker_count = 1
    policy_counts = Counter()
    success = True

    # Run processes using ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        for account in accounts_iterator(accounts_config):
            for region in resolve_regions(account.get('regions', ['all']), account):
                future = executor.submit(
                    run_account_in_memory,
                    account=account,
                    region=region,
                    policy_data=POLICY_DATA,
                    output_dir=".log",
                    granularity=granularity
                )
                futures[future] = (account, region)

        # Collect the results and log failures
        for f in as_completed(futures):
            a, r = futures[f]
            try:
                account_region_pcounts, account_region_success = f.result()
                for p in account_region_pcounts:
                    policy_counts[p] += account_region_pcounts[p]

                if not account_region_success:
                    success = False
            except Exception as e:
                log.warning("Error running policy in %s @ %s exception: %s", a['name'], r, e)
                success = False

    log.info("Policy resource counts %s" % policy_counts)

    if not success:
        raise ValueError("Metrics collection completed with errors.")


if __name__ == "__main__":
    run_metrics_collector()

