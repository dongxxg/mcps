"""Capability backends: reader / analyzer / writer.

Policy-unaware by design: these modules implement Excel read / analyze / write
capability ONLY. Safety (path sandboxing, read-only toggles), audit, and
redaction are deliberately NOT handled here — Phase 2 lifts them to the
tool / caller layer. Keeping the backends free of policy is what lets Phase 2
wrap them as MCP tools with zero rework to this layer.
"""
