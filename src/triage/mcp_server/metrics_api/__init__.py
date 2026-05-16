"""metrics-api namespace — read-only CloudWatch metric queries.

Importing this package eagerly imports each tool module so the FastMCP
decorators register tools on the shared server instance.
"""

from . import get_metric_statistics  # noqa: F401  (registration side-effect)
