"""Strava MCP Local Mirror.

A locally-run process that authorizes once to Strava, backfills the athlete's
entire history (with full per-activity enrichment including streams), polls for
new activities, and serves that data to AI agents over a loopback FastMCP HTTP
server whose tools are pure SQLite reads. See specs/001-strava-mcp-mirror/.
"""

__version__ = "0.1.0"
