"""serverOps — an MCP server for operating on multiple remote services.

Connects to named SSH hosts, Docker daemons, Kubernetes clusters, and databases
and exposes operations on them as MCP tools. Tools reference connections by name
(no raw credentials ever cross the tool boundary).
"""

__version__ = "0.1.0"
