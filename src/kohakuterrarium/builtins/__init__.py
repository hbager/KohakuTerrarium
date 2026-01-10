"""
Builtins module - all built-in components for the framework.

Contains:
- tools: Built-in tool implementations (bash, python, read, write, edit, glob, grep)
- subagents: Built-in sub-agent configurations (explore, plan, memory_read, memory_write)
- skills: Skill documentation files
"""

from kohakuterrarium.builtins.subagents import (
    BUILTIN_SUBAGENTS,
    get_builtin_subagent_config,
    list_builtin_subagents,
)
from kohakuterrarium.builtins.tools import (
    BashTool,
    EditTool,
    GlobTool,
    GrepTool,
    PythonTool,
    ReadTool,
    WriteTool,
    get_builtin_tool,
    is_builtin_tool,
    list_builtin_tools,
    register_builtin,
)

__all__ = [
    # Tool registry
    "register_builtin",
    "get_builtin_tool",
    "list_builtin_tools",
    "is_builtin_tool",
    # Tool implementations
    "BashTool",
    "PythonTool",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "GlobTool",
    "GrepTool",
    # Sub-agent registry
    "BUILTIN_SUBAGENTS",
    "get_builtin_subagent_config",
    "list_builtin_subagents",
]
