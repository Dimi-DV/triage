"""logs-api namespace — read-only CloudWatch Logs queries.

Importing this package eagerly imports each tool module so the FastMCP
decorators register tools on the shared server instance.
"""

from . import filter_log_events  # noqa: F401  (registration side-effect)
