"""
Skill/Documentation loader with frontmatter YAML support.

Loads markdown files with optional YAML frontmatter for metadata.

Format:
```
---
name: tool_name
description: One-line description
category: builtin
---

# Full Documentation

...markdown content...
```
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SkillDoc:
    """Parsed skill/tool documentation."""

    name: str
    description: str
    content: str
    category: str = "custom"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def full_doc(self) -> str:
        """Get full documentation (frontmatter + content)."""
        return self.content


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Parse YAML frontmatter from markdown text.

    Args:
        text: Markdown text potentially with frontmatter

    Returns:
        (metadata_dict, content_without_frontmatter)
    """
    text = text.strip()

    # Check for frontmatter delimiter
    if not text.startswith("---"):
        return {}, text

    # Find end of frontmatter
    end_idx = text.find("---", 3)
    if end_idx == -1:
        return {}, text

    # Extract frontmatter YAML
    frontmatter_text = text[3:end_idx].strip()
    content = text[end_idx + 3 :].strip()

    # Parse YAML
    try:
        metadata = yaml.safe_load(frontmatter_text)
        if not isinstance(metadata, dict):
            metadata = {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse frontmatter", error=str(e))
        metadata = {}

    return metadata, content


def load_skill_doc(path: Path | str) -> SkillDoc | None:
    """
    Load a skill/tool documentation file.

    Args:
        path: Path to markdown file

    Returns:
        SkillDoc or None if file not found
    """
    path = Path(path)

    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
        metadata, content = parse_frontmatter(text)

        return SkillDoc(
            name=metadata.get("name", path.stem),
            description=metadata.get("description", ""),
            content=content,
            category=metadata.get("category", "custom"),
            tags=metadata.get("tags", []),
            metadata={
                k: v
                for k, v in metadata.items()
                if k not in ("name", "description", "category", "tags")
            },
        )
    except Exception as e:
        logger.error("Failed to load skill doc", path=str(path), error=str(e))
        return None


def load_skill_docs_from_dir(directory: Path | str) -> dict[str, SkillDoc]:
    """
    Load all skill docs from a directory.

    Args:
        directory: Path to directory containing .md files

    Returns:
        Dict mapping skill name to SkillDoc
    """
    directory = Path(directory)
    docs = {}

    if not directory.exists():
        return docs

    for path in directory.glob("*.md"):
        doc = load_skill_doc(path)
        if doc:
            docs[doc.name] = doc

    return docs
