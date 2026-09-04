from kohakuterrarium.prompt import rules
from kohakuterrarium.prompt.aggregator import aggregate_system_prompt


def test_build_rule_prompt_loads_project_and_agent_rules(tmp_path, monkeypatch):
    global_rule = tmp_path / "global-rule.md"
    project_dir = tmp_path / "project"
    agent_dir = tmp_path / "agent"
    project_dir.mkdir()
    agent_dir.mkdir()
    global_rule.write_text("global rule", encoding="utf-8")
    (project_dir / "rule.md").write_text("project rule", encoding="utf-8")
    (agent_dir / "rule.md").write_text("agent rule", encoding="utf-8")
    monkeypatch.setattr(rules, "get_global_rule_path", lambda: global_rule)

    prompt = rules.build_rule_prompt(project_dir=project_dir, agent_path=agent_dir)

    assert "global rule" in prompt
    assert "project rule" in prompt
    assert "agent rule" in prompt


def test_aggregate_system_prompt_appends_project_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "get_global_rule_path", lambda: tmp_path / "missing.md")
    (tmp_path / "rule.md").write_text("follow project rule", encoding="utf-8")

    prompt = aggregate_system_prompt(
        "base",
        include_tools=False,
        include_hints=False,
        extra_context={"pwd": str(tmp_path)},
    )

    assert prompt.startswith("base")
    assert "## User Rules" in prompt
    assert "follow project rule" in prompt
