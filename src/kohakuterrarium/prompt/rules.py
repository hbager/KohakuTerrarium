"""User rule prompt loading for agents and sub-agents."""

from pathlib import Path

from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)

RULE_FILE_NAME = "rule.md"


def get_global_rule_path() -> Path:
    return Path.home() / ".kohakuterrarium" / RULE_FILE_NAME


def discover_rule_files(
    *,
    project_dir: Path | None = None,
    agent_path: Path | None = None,
) -> list[tuple[str, Path]]:
    candidates = [
        ("Global rule.md", get_global_rule_path()),
    ]

    if project_dir is not None:
        candidates.append(("Project rule.md", project_dir / RULE_FILE_NAME))
    if agent_path is not None:
        candidates.append(("Agent rule.md", agent_path / RULE_FILE_NAME))

    seen: set[Path] = set()
    files: list[tuple[str, Path]] = []
    for label, path in candidates:
        resolved = path.expanduser().resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        files.append((label, resolved))

    return files


def build_rule_prompt(
    *,
    project_dir: Path | None = None,
    agent_path: Path | None = None,
) -> str:
    sections: list[str] = []
    seen_contents: set[str] = set()

    for label, path in discover_rule_files(project_dir=project_dir, agent_path=agent_path):
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read rule file", path=str(path), error=str(exc))
            continue
        if not content or content in seen_contents:
            continue
        seen_contents.add(content)
        sections.append(f"### {label}\n\n{content}")

    if not sections:
        return ""

    return "\n\n".join(
        [
            "## User Rules",
            "These rules apply unless higher-priority system or developer instructions conflict.",
            *sections,
        ]
    )


def append_rule_prompt(
    base_prompt: str,
    *,
    project_dir: Path | None = None,
    agent_path: Path | None = None,
) -> str:
    rule_prompt = build_rule_prompt(project_dir=project_dir, agent_path=agent_path)
    if not rule_prompt:
        return base_prompt
    if not base_prompt:
        return rule_prompt
    return f"{base_prompt.rstrip()}\n\n{rule_prompt}"
