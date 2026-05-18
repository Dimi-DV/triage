"""ecs-api namespace — read-only inspection of ECS + the ALB/NLB target
groups the workload sits behind.

Importing this package eagerly imports each tool module so the FastMCP
decorators register tools on the shared server instance.
"""

from . import (
    describe_target_health,  # noqa: F401  (registration side-effect)
    describe_task_definition,  # noqa: F401  (registration side-effect)
)
