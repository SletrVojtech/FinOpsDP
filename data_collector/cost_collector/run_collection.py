"""
Cost Collection Module.

This module is responsible for orchestrating the collection of cloud provider
cost exports. It downloads billing and cost management datasets for AWS and Azure.
"""

import yaml
import logging
import os
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from c7n_org.cli import init, accounts_iterator
from cost_collector.downloaders import run_aws_worker_process, run_azure_worker_process
from rabbitmq.connector import RabbitMQClient
from cost_collector.data_loader import CostDataLoader
from registry import register_collector

log = logging.getLogger("cost_export_downloader")

@register_collector("costs", help_text="Download CostExports from Cloud Billing API and send to RMQ")
def run_cost_downloads(output_dir="/tmp/cost_exports", days_back=7):
    """
    Download CostExports from Cloud Billing API and send them to RabbitMQ.

    This function reads account and cost export configurations, concurrently
    downloads the required cost exports using a process pool, and publishes
    the downloaded files to the data ingestion queue.

    Args:
        output_dir (str, optional): The directory where downloaded exports will be temporarily stored. Defaults to "/tmp/cost_exports".
        days_back (int, optional): The number of days of history to process from the exports. Defaults to 7.

    Raises:
        FileNotFoundError: If the required configuration files are not found.
        RuntimeError: If any of the download tasks fail.
    """
    try:
        # Load AWS accounts
        accounts_config, _, _ = init(
            config='.conf/accounts.yml',
            use=None, debug=False, verbose=False,
            accounts=None, tags=None, policies=None
        )
        
        # Load Cost Export definitions
        with open('.conf/cost_exports.yml', 'r') as f:
            cost_config = yaml.safe_load(f)
    except FileNotFoundError as e:
        log.error(f"Configuration file missing: {e}")
        raise FileNotFoundError(f"Missing configuration file: {e}")

    # Map Account ID to export name 
    aws_exports_map = {
        str(item['account_id']): item 
        for item in cost_config.get('aws', [])
    }

    worker_count = 1
    success = True
    all_downloaded_files = []

    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        
        # Iterate over AWS
        for account in accounts_iterator(accounts_config):
            acc_id = str(account.get('account_id'))
            
            if acc_id in aws_exports_map:
                export_info = aws_exports_map[acc_id]
                future = executor.submit(
                    run_aws_worker_process,
                    account=account,
                    export_name=export_info['export_name'],
                    region=export_info.get('region', 'us-east-1'),
                    output_dir=output_dir
                )
                futures[future] = f"AWS - {account.get('name', acc_id)}"
        
        # Iterate over Azure
        for azure_info in cost_config.get('azure', []):
            export_name = azure_info.get('export_name')
            
            if 'billing_id' in azure_info:
                scope_type = 'billing'
                scope_id = azure_info['billing_id']
            elif 'subscription_id' in azure_info:
                scope_type = 'subscription'
                scope_id = azure_info['subscription_id']
            else:
                log.error("Azure configuration has to have either 'billing_id' or 'subscription_id' scope.")
                continue
            
            future = executor.submit(
                run_azure_worker_process,
                scope_type=scope_type,
                scope_id=scope_id,
                export_name=export_name,
                output_dir=output_dir
            )
            futures[future] = f"Azure - {scope_type} - {scope_id[:8]}"

        for f in as_completed(futures):
            task_name = futures[f]
            try:
                files, task_success = f.result()
                if files:
                    all_downloaded_files.extend(files)
                if not task_success:
                    success = False
            except Exception as exc:
                log.error(f"Critical error during {task_name}: {exc}")
                success = False

    log.info(f"Download finished, total files: {len(all_downloaded_files)}")
    
    if all_downloaded_files:
        log.info("Loading files into RabbitMQ.")
        with RabbitMQClient() as mq_client:
            loader = CostDataLoader(rmq_client=mq_client, queue_name="data_ingestion")

            for folder_name in os.listdir(output_dir):
                folder_path = os.path.join(output_dir, folder_name)
                
                if os.path.isdir(folder_path):
                    # include csv and csv.gz
                    file_pattern = os.path.join(folder_path, "*.csv*")
                    loader.process_and_publish(file_pattern, days_back=days_back)
                    shutil.rmtree(folder_path)
        log.info("Finished loading files into RabbitMQ.")

    if not success:
        raise RuntimeError("One or more download tasks failed.")

if __name__ == "__main__":
    run_cost_downloads()