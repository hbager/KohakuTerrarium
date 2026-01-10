"""
Builtin skills - default documentation for builtin tools and subagents.

These files are packaged with the library and serve as default documentation.
Users can override them by placing files in their agent's prompts/tools/ folder.
"""

from pathlib import Path

# Path to builtin skills directory
BUILTIN_SKILLS_DIR = Path(__file__).parent


def get_builtin_tool_doc(name: str) -> str | None:
    """
    Get builtin tool documentation by name.

    Args:
        name: Tool name (e.g., "bash", "read")

    Returns:
        Documentation content or None if not found
    """
    doc_path = BUILTIN_SKILLS_DIR / "tools" / f"{name}.md"
    if doc_path.exists():
        return doc_path.read_text(encoding="utf-8")
    return None


def get_builtin_subagent_doc(name: str) -> str | None:
    """
    Get builtin subagent documentation by name.

    Args:
        name: Subagent name

    Returns:
        Documentation content or None if not found
    """
    doc_path = BUILTIN_SKILLS_DIR / "subagents" / f"{name}.md"
    if doc_path.exists():
        return doc_path.read_text(encoding="utf-8")
    return None
