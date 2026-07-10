"""Unit tests for :mod:`kohakuterrarium.terrarium.resume`.

The two real branches load actual Agents from a saved store, which we
short-circuit by patching :func:`resume_agent` and
:func:`detect_session_type`. Engine + Creature integration stays real.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kohakuterrarium.bootstrap import agent_init as _agent_init
from kohakuterrarium.bootstrap import llm as _bootstrap_llm
from kohakuterrarium.builtins.inputs.none import NoneInput
from kohakuterrarium.errors import SessionLockedError
from kohakuterrarium.terrarium import resume as resume_mod
from kohakuterrarium.testing.llm import ScriptedLLM
from kohakuterrarium.testing.terrarium import TestTerrariumBuilder, _FakeAgent
from kohakuterrarium.terrarium.creature_host import Creature

# ── _resolve_store_path ───────────────────────────────────────


class TestResolveStorePath:
    def test_session_store_object_uses_path(self):
        ss = SimpleNamespace(path="/some/p.kohakutr")
        out = resume_mod._resolve_store_path(ss)
        assert isinstance(out, Path)

    def test_session_store_object_fallback_to_str(self):
        class _Bare:
            def __str__(self):
                return "/fallback.kohakutr"

        out = resume_mod._resolve_store_path(_Bare())
        # No ``path`` attr → falls back to str(store).
        assert isinstance(out, Path)

    def test_string_path(self):
        out = resume_mod._resolve_store_path("/some/file.kohakutr")
        assert out == Path("/some/file.kohakutr")

    def test_path_object(self):
        out = resume_mod._resolve_store_path(Path("/some/file.kohakutr"))
        assert out == Path("/some/file.kohakutr")


# ── resume_into_engine dispatch ───────────────────────────────


class TestResumeIntoEngine:
    async def test_unknown_session_type_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "bogus")
        t = await TestTerrariumBuilder().build()
        try:
            with pytest.raises(ValueError, match="Unknown saved-session"):
                await resume_mod.resume_into_engine(t, tmp_path / "x.kohakutr")
        finally:
            await t.shutdown()

    async def test_agent_path_dispatches(self, monkeypatch, tmp_path):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "agent")

        fake_agent = _FakeAgent(name="alice")
        fake_agent.config = SimpleNamespace(name="alice")
        fake_store = SimpleNamespace()
        captured: dict = {}

        def _resume_agent(
            path,
            pwd_override=None,
            io_mode=None,
            llm=None,
            *,
            input_module=None,
            output_module=None,
        ):
            captured["input_module"] = input_module
            return fake_agent, fake_store

        monkeypatch.setattr(resume_mod, "resume_agent", _resume_agent)

        t = await TestTerrariumBuilder().build()
        try:
            # Stub attach_session so it doesn't need a real store.
            t.attach_session = AsyncMock()
            gid = await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            assert gid
            t.attach_session.assert_awaited()
            # Engine-hosted resume MUST suppress the config's own IO loop
            # — the creature is driven by the engine / attach WebSocket,
            # never a stdin reader. Without this a worker-side resume
            # boots ``input: cli`` with no TTY and wedges the worker.
            assert isinstance(captured["input_module"], NoneInput)
        finally:
            await t.shutdown()

    async def test_agent_metadata_failure_closes_writer_store(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "agent")
        closed = False

        def close_store():
            nonlocal closed
            closed = True

        fake_store = SimpleNamespace(
            load_meta=lambda: (_ for _ in ()).throw(RuntimeError("meta failed")),
            close=close_store,
        )
        monkeypatch.setattr(
            resume_mod, "_open_store_with_migration", lambda p, **kwargs: fake_store
        )

        t = await TestTerrariumBuilder().build()
        try:
            with pytest.raises(RuntimeError, match="meta failed"):
                await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            assert closed is True
        finally:
            await t.shutdown()

    async def test_agent_attach_failure_stops_graph_and_closes_store(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "agent")
        fake_agent = _FakeAgent(name="alice")
        fake_agent.config = SimpleNamespace(name="alice")
        closed = False

        def close_store():
            nonlocal closed
            closed = True

        fake_store = SimpleNamespace(close=close_store)
        monkeypatch.setattr(
            resume_mod, "resume_agent", lambda *args, **kwargs: (fake_agent, fake_store)
        )

        t = await TestTerrariumBuilder().build()
        real_stop_graph = t.stop_graph
        t.stop_graph = AsyncMock(wraps=real_stop_graph)
        t.attach_session = AsyncMock(side_effect=RuntimeError("attach failed"))
        try:
            with pytest.raises(RuntimeError, match="attach failed"):
                await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            t.stop_graph.assert_awaited_once()
            assert closed is True
        finally:
            await t.shutdown()

    async def test_runtime_group_partial_failure_stops_graph_and_closes_store(
        self, monkeypatch
    ):
        closed = False

        def close_store():
            nonlocal closed
            closed = True

        fake_store = SimpleNamespace(close=close_store)
        meta = {
            "config_path": "/tmp/creature",
            "config_snapshot": {"name": "generic"},
            "pwd": ".",
            "agents": ["alice", "bob"],
        }
        fake_agent = _FakeAgent(name="generic")
        fake_agent.config = SimpleNamespace(name="generic")
        monkeypatch.setattr(resume_mod, "_rebuild_agent", lambda **kwargs: fake_agent)
        monkeypatch.setattr(resume_mod, "inject_saved_state", lambda *args: None)

        t = await TestTerrariumBuilder().build()
        real_add_creature = t.add_creature
        calls = 0

        async def fail_second_add(*args, **kwargs):
            nonlocal calls
            calls += 1
            assert kwargs.get("session") is False
            if calls == 2:
                raise RuntimeError("second add failed")
            return await real_add_creature(*args, **kwargs)

        real_stop_graph = t.stop_graph
        t.add_creature = fail_second_add
        t.stop_graph = AsyncMock(wraps=real_stop_graph)
        try:
            with pytest.raises(RuntimeError, match="second add failed"):
                await resume_mod._resume_runtime_group_into_engine(
                    t, fake_store, meta, pwd=None, llm=None
                )
            t.stop_graph.assert_awaited_once()
            assert closed is True
        finally:
            await t.shutdown()

    async def test_terrarium_path_dispatches(self, monkeypatch, tmp_path):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "terrarium")

        fake_store = SimpleNamespace(
            load_meta=lambda: {
                "config_path": "/tmp/recipe.yaml",
                "pwd": ".",
                "agents": ["alice"],
            },
            update_status=lambda s: None,
        )

        monkeypatch.setattr(
            resume_mod, "_open_store_with_migration", lambda p, **_kw: fake_store
        )

        from kohakuterrarium.terrarium.config import TerrariumConfig

        fake_config = TerrariumConfig(name="t", creatures=[], channels=[])
        monkeypatch.setattr(resume_mod, "load_terrarium_config", lambda p: fake_config)

        injects = []

        def _inject(agent, store, name):
            injects.append(name)

        monkeypatch.setattr(resume_mod, "inject_saved_state", _inject)

        t = await TestTerrariumBuilder().build()
        try:
            t.attach_session = AsyncMock()
            gid = await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            assert gid
            t.attach_session.assert_awaited()
        finally:
            await t.shutdown()

    async def test_terrarium_resume_missing_config_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "terrarium")

        closed = False

        def close_store():
            nonlocal closed
            closed = True

        fake_store = SimpleNamespace(
            load_meta=lambda: {"config_path": ""},
            update_status=lambda s: None,
            close=close_store,
        )
        monkeypatch.setattr(
            resume_mod, "_open_store_with_migration", lambda p, **_kw: fake_store
        )

        t = await TestTerrariumBuilder().build()
        try:
            with pytest.raises(ValueError, match="no config_path"):
                await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            assert closed is True
        finally:
            await t.shutdown()

    async def test_terrarium_apply_failure_stops_partial_graph(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "terrarium")
        closed = False

        def close_store():
            nonlocal closed
            closed = True

        fake_store = SimpleNamespace(
            load_meta=lambda: {
                "config_path": "/tmp/recipe.yaml",
                "pwd": ".",
                "agents": ["alice"],
            },
            close=close_store,
        )
        monkeypatch.setattr(
            resume_mod, "_open_store_with_migration", lambda p, **kwargs: fake_store
        )
        monkeypatch.setattr(resume_mod, "load_terrarium_config", lambda p: object())

        t = await TestTerrariumBuilder().build()
        real_add_creature = t.add_creature
        existing_agent = _FakeAgent(name="existing")
        existing_agent.config = SimpleNamespace(name="existing")
        existing_creature = Creature(
            creature_id="existing",
            name="existing",
            agent=existing_agent,
            config=existing_agent.config,
        )
        await real_add_creature(existing_creature, start=False, session=False)
        existing_graph_id = existing_creature.graph_id
        partial_graph_id = None

        async def fail_after_graph_created(*args, **kwargs):
            nonlocal partial_graph_id
            agent = _FakeAgent(name="partial")
            agent.config = SimpleNamespace(name="partial")
            creature = Creature(
                creature_id="partial",
                name="partial",
                agent=agent,
                config=agent.config,
            )
            await real_add_creature(creature, start=False, session=False)
            partial_graph_id = creature.graph_id
            kwargs["_on_graph_created"](partial_graph_id)
            raise RuntimeError("recipe build failed")

        real_stop_graph = t.stop_graph
        t.apply_recipe = fail_after_graph_created
        t.stop_graph = AsyncMock(wraps=real_stop_graph)
        try:
            with pytest.raises(RuntimeError, match="recipe build failed"):
                await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            t.stop_graph.assert_awaited_once_with(partial_graph_id)
            assert existing_graph_id in {graph.graph_id for graph in t.list_graphs()}
            assert closed is True
        finally:
            await t.shutdown()

    async def test_terrarium_failure_after_build_stops_new_graph(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "terrarium")
        fake_store = SimpleNamespace(
            load_meta=lambda: {
                "config_path": "/tmp/recipe.yaml",
                "pwd": ".",
                "agents": ["alice"],
            },
            update_status=lambda status: None,
            close=lambda: None,
        )
        monkeypatch.setattr(
            resume_mod, "_open_store_with_migration", lambda p, **kw: fake_store
        )
        monkeypatch.setattr(resume_mod, "load_terrarium_config", lambda p: object())

        t = await TestTerrariumBuilder().build()
        graph = SimpleNamespace(graph_id="new", creature_ids=[])
        t.apply_recipe = AsyncMock(return_value=graph)
        t.stop_graph = AsyncMock()
        monkeypatch.setattr(
            resume_mod,
            "_topo_snap",
            SimpleNamespace(replay=AsyncMock(side_effect=RuntimeError("replay failed"))),
        )
        t.attach_session = AsyncMock()
        try:
            with pytest.raises(RuntimeError, match="replay failed"):
                await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            t.stop_graph.assert_awaited_once_with("new")
        finally:
            await t.shutdown()

    async def test_terrarium_resume_with_saved_agents_alignment(
        self, monkeypatch, tmp_path
    ):
        # Saved agents list is ["bob"] but the rebuild produces "alice".
        # Positional consumption should rename the rebuilt creature to "bob".
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "terrarium")
        fake_store = SimpleNamespace(
            load_meta=lambda: {
                "config_path": "/tmp/recipe.yaml",
                "pwd": ".",
                "agents": ["bob"],
            },
            update_status=lambda s: None,
        )
        monkeypatch.setattr(
            resume_mod, "_open_store_with_migration", lambda p, **_kw: fake_store
        )

        from kohakuterrarium.terrarium.config import (
            CreatureConfig,
            TerrariumConfig,
        )

        fake_config = TerrariumConfig(
            name="t",
            creatures=[
                CreatureConfig(
                    name="alice",
                    config_data={"name": "alice"},
                    base_dir=Path("."),
                )
            ],
            channels=[],
        )
        monkeypatch.setattr(resume_mod, "load_terrarium_config", lambda p: fake_config)

        # Stub apply_recipe to build a fake creature directly.

        async def _fake_apply_recipe(config, pwd=None, **_):
            t = engine_holder["t"]
            agent = _FakeAgent(name="alice")
            agent.config = SimpleNamespace(name="alice")
            agent.attach_session_store = lambda s: None
            c = Creature(
                creature_id="alice",
                name="alice",
                agent=agent,
                config=agent.config,
            )
            await t.add_creature(c, start=False)
            return t._topology.graphs[c.graph_id]

        monkeypatch.setattr(resume_mod, "inject_saved_state", lambda *a, **kw: None)

        engine_holder = {}
        t = await TestTerrariumBuilder().build()
        engine_holder["t"] = t
        t.apply_recipe = _fake_apply_recipe
        t.attach_session = AsyncMock()
        try:
            await resume_mod.resume_into_engine(t, tmp_path / "saved.kohakutr")
            # The creature got renamed positionally to "bob".
            c = t.get_creature("alice")
            assert c.name == "bob"
        finally:
            await t.shutdown()

    async def test_runtime_group_agent_path_rebuilds_all_saved_agents(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "agent")

        def _fake_create(config, llm=None):
            return ScriptedLLM(["OK"])

        monkeypatch.setattr(_bootstrap_llm, "create_llm_provider", _fake_create)
        monkeypatch.setattr(_agent_init, "create_llm_provider", _fake_create)

        from kohakuterrarium.session.store import SessionStore

        store_path = tmp_path / "group.kohakutr"
        config_dir = tmp_path / "creature"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "name: generic\n"
            "controller:\n"
            "  tool_format: bracket\n"
            "  include_tools_in_prompt: false\n"
            "  include_hints_in_prompt: false\n"
            "system_prompt: test\n"
            "input:\n"
            "  type: none\n"
            "output:\n"
            "  type: none\n",
            encoding="utf-8",
        )
        store = SessionStore(store_path)
        try:
            store.init_meta(
                session_id="group",
                config_type="terrarium",
                config_path=str(config_dir),
                pwd=str(tmp_path),
                agents=["alice", "bob"],
            )
            store.save_conversation("alice", [{"role": "user", "content": "a"}])
            store.save_conversation("bob", [{"role": "user", "content": "b"}])
            store.flush()
        finally:
            store.close()

        t = await TestTerrariumBuilder().build()
        try:
            t.attach_session = AsyncMock(wraps=t.attach_session)
            gid = await resume_mod.resume_into_engine(t, store_path)
            graph = t._topology.graphs[gid]
            assert len(graph.creature_ids) == 2
            assert {t.get_creature(cid).name for cid in graph.creature_ids} == {
                "alice",
                "bob",
            }
            t.attach_session.assert_awaited_once()
            with pytest.raises(SessionLockedError):
                SessionStore(store_path, writer_lock=True)
        finally:
            await t.shutdown()
        reopened = SessionStore(store_path, writer_lock=True)
        reopened.close(update_status=False)

    async def test_terrarium_resume_no_autosession_ghost(self, monkeypatch, tmp_path):
        # REGRESSION PIN: resuming a terrarium into an engine that has
        # autosession configured (``Terrarium(session_dir=...)`` — every
        # API-server engine) must NOT let ``apply_recipe`` mint a fresh
        # ``<new_gid>.kohakutr``.  The saved store attaches right after,
        # so the minted file would be an instantly-orphaned ghost stuck
        # at ``status="running"`` in the saved-session list, plus a
        # leaked open SQLite handle.
        monkeypatch.setattr(resume_mod, "detect_session_type", lambda p: "terrarium")
        fake_store = SimpleNamespace(
            load_meta=lambda: {
                "config_path": "/tmp/recipe.yaml",
                "pwd": ".",
                "agents": [],
            },
            update_status=lambda s: None,
            close=lambda: None,
        )
        monkeypatch.setattr(
            resume_mod, "_open_store_with_migration", lambda p, **_kw: fake_store
        )

        from kohakuterrarium.terrarium.config import TerrariumConfig
        from kohakuterrarium.terrarium.engine import Terrarium

        fake_config = TerrariumConfig(name="t", creatures=[], channels=[])
        monkeypatch.setattr(resume_mod, "load_terrarium_config", lambda p: fake_config)
        monkeypatch.setattr(resume_mod, "inject_saved_state", lambda *a, **kw: None)

        session_dir = tmp_path / "sessions"
        session_dir.mkdir()
        t = Terrarium(session_dir=str(session_dir))
        try:
            # Real ``apply_recipe`` (empty recipe) + real autosession
            # machinery — only ``attach_session`` is stubbed so the
            # SimpleNamespace store does not have to behave like a
            # SessionStore.
            t.attach_session = AsyncMock()
            gid = await resume_mod.resume_into_engine(
                t, tmp_path / "saved.kohakutr"
            )
            # No ghost store file was minted next to the saved session;
            # ownership tracks only the resumed graph so shutdown closes it.
            assert list(session_dir.glob("*.kohakutr")) == []
            assert t._owned_sessions == {gid}
        finally:
            await t.shutdown()
