"""MCP tool modules. Each module exposes ``register(mcp, registry)``.

Kept empty on purpose: ``server.create_app`` imports and registers each tool
module explicitly so the dependency surface is obvious and easy to extend.
"""
