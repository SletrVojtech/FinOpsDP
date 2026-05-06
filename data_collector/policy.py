"""
Cloud Custodian Policy Execution Modes.

This module provides custom execution modes for Cloud Custodian, specifically
the InMemoryPullMode which allows running policies without persisting
intermediate resource data to disk.
"""

import time
from typing import List, Dict, Any
from c7n import utils
from c7n.exceptions import ResourceLimitExceeded
from c7n.policy import PullMode, execution
from c7n.version import version


@execution.register('in-memory-pull')
class InMemoryPullMode(PullMode):
    """
    Custom Cloud Custodian Pull mode that skips writing output files to disk.

    """
    schema = utils.type_schema('in-memory-pull')

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        """
        Executes the policy in-memory.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            List[Dict[str, Any]]: The list of resources matched by the policy.

        Raises:
            ResourceLimitExceeded: If the number of resources exceeds configured limits.
        """
        if not self.policy.is_runnable():
            return []

        with self.policy.ctx as ctx:
            self.policy.log.debug(
                "Running policy:%s resource:%s region:%s c7n:%s",
                self.policy.name,
                self.policy.resource_type,
                self.policy.options.region or 'default',
                version,
            )

            start_time = time.time()
            try:
                resources = self.policy.resource_manager.resources()
            except ResourceLimitExceeded as e:
                self.policy.log.error(str(e))
                ctx.metrics.put_metric(
                    'ResourceLimitExceeded', e.selection_count, "Count"
                )
                raise

            duration = time.time() - start_time
            
            # Log execution summary
            self.policy.log.info(
                "policy:%s resource:%s region:%s count:%d time:%.2f",
                self.policy.name,
                self.policy.resource_type,
                self.policy.options.region,
                len(resources),
                duration,
            )
            
            # Put standard metrics
            ctx.metrics.put_metric("ResourceCount", len(resources), "Count", Scope="Policy")
            ctx.metrics.put_metric("ResourceTime", duration, "Seconds", Scope="Policy")

            if not resources:
                return []

            return resources