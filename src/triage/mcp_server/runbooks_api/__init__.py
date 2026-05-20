"""runbooks-api MCP namespace.

Eager imports trigger @mcp.tool decorator registration on the FastMCP
instance at server startup. Add new tools to this list when scaffolded.
"""

from . import lookup_runbook, post_to_slack  # noqa: F401  (registration side-effect)
