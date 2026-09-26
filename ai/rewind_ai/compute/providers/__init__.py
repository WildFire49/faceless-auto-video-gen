"""Accelerator implementations.

Every module here registers itself with ``core.registry`` on import. The
container sweeps this package at startup, so adding an accelerator never
requires editing an import list (SPEC.md 14.2).
"""
