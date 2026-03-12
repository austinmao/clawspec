# MCP

MCP integration is intentionally deferred in ClawSpec v0.1.

What ships in v0.1:

- the standalone CLI
- the Python API
- the OpenClaw skill wrapper in `skill/`

What does not ship yet:

- an MCP server
- Claude Code tool exposure
- any remote control-plane integration

Planned direction for v0.2:

- expose validation, run, init, and coverage operations as MCP tools
- return structured reports directly over MCP
- keep the CLI and Python API as the stable base layer

