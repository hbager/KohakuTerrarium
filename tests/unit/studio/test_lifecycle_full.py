"""Full coverage tests for :mod:`kohakuterrarium.studio.sessions.lifecycle`.

Real ``Terrarium`` engine + ``LocalTerrariumService`` driven via
``TestTerrariumBuilder``; no LLM is involved.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kohakuterrarium.studio.sessions import lifecycle
from kohakuterrarium.terrarium.engine import Terrarium
from kohakuterrarium.terrarium.service import LocalTerrariumService
from kohakuterrarium.testing.terrarium import (
    TestTerrariumBuilder,
    _FakeAgent,
)

# Session bookkeeping is instance-scoped (studio.sessions.registry) —
# each test builds its own engine/service, so no module-state reset is
# needed between tests.


# ── start_creature (local, in-memory config) ──────────────────


class TestStartCreatureLocal:
    async def test_with_in_memory_config(self, monkeypatch, tmp_path):
        engine = Terrarium()
        svc = LocalTerrariumService(engine)
        from kohakuterrarium.core.config_types import AgentConfig
        from kohakuterrarium.terrarium.creature_host import Creature

        # Stub engine.add_creature to return a fake creature.
        agent = _FakeAgent(name="alice")
        agent.config = SimpleNamespace(name="alice")
        agent.session_store = None
        agent.executor = None
        agent.attach_session_store = lambda s: None
        fake_creature = Creature(
            creature_id="cid-x",
            name="alice",
            agent=agent,
            graph_id="g1",
            config=agent.config,
            is_privileged=True,
        )

        async def _fake_add(cfg, *args, **kw):
            return fake_creature

        engine.add_creature = _fake_add
        engine._session_stores = {}
        engine._environments = {}
        engine.list_graphs = lambda: [
            SimpleNamespace(graph_id="g1", creature_ids={"cid-x"})
        ]
        engine.get_creature = lambda cid: fake_creature
        engine._creatures = {"cid-x": fake_creature}
        # Don't actually open a session store file — patch SessionStore.
        monkeypatch.setattr(
            lifecycle,
            "SessionStore",
            lambda p: SimpleNamespace(
                meta={},
                init_meta=lambda **kw: None,
                save=lambda: None,
                close=lambda: None,
            ),
        )
        try:
            cfg = AgentConfig(name="alice", system_prompt="x")
            sess = await lifecycle.start_creature(svc, config=cfg)
            # The fresh creature joined graph g1 → that is the session id.
            assert sess.session_id == "g1"
            assert sess.name == "alice"
            assert sess.home_node == "_host"
        finally:
            await engine.shutdown()

    async def test_remote_on_node_synthesizes_session(self, monkeypatch):
        # When on_node != "_host", takes the remote path.
        engine = Terrarium()
        svc = LocalTerrariumService(engine)
        from kohakuterrarium.terrarium.service import CreatureInfo

        info = CreatureInfo(
            creature_id="cid-r",
            name="bob",
            graph_id="g-remote",
            is_running=True,
            is_privileged=False,
            parent_creature_id=None,
            listen_channels=(),
            send_channels=(),
        )

        async def _add(cfg, **kw):
            return info

        # Replace the multi-node-like path: monkey-patch add_creature on
        # the service to bypass on_node check.
        svc.add_creature = _add
        try:
            sess = await lifecycle.start_creature(
                svc, config=SimpleNamespace(name="bob"), on_node="worker-1"
            )
            assert sess.home_node == "worker-1"
            # _meta entry retained.
            assert sess.session_id in lifecycle.meta_for(svc)
        finally:
            await engine.shutdown()

    async def test_neither_path_raises(self):
        engine = Terrarium()
        svc = LocalTerrariumService(engine)
        try:
            with pytest.raises(ValueError):
                await lifecycle.start_creature(svc)
        finally:
            await engine.shutdown()


# ── attach_session_store_for_creature ────────────────────────


class TestAttachSessionStoreForCreature:
    async def test_attaches_new_store(self, tmp_path, monkeypatch):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            monkeypatch.setattr(lifecycle, "_session_dir", lambda: str(tmp_path))
            creature = t.get_creature("alice")
            # Track attach calls.
            creature.agent.attach_session_store = lambda s: setattr(
                creature.agent, "_attached", s
            )
            lifecycle.attach_session_store_for_creature(
                svc, creature, config_path="/tmp/cfg.yaml"
            )
            assert creature.agent._attached is not None
            sid = creature.graph_id
            assert sid in lifecycle.stores_for(svc)
            # Cleanup
            store = lifecycle.stores_for(svc)[sid]
            store.close()
        finally:
            await t.shutdown()

    async def test_reuses_existing_store(self, tmp_path):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            creature = t.get_creature("alice")
            attached = []
            creature.agent.attach_session_store = lambda s: attached.append(s)
            # Pre-populate engine's _session_stores.
            from kohakuterrarium.session.store import SessionStore

            sid = creature.graph_id
            existing = SessionStore(str(tmp_path / "pre.kohakutr"))
            existing.init_meta(
                session_id=sid,
                config_type="agent",
                config_path="",
                pwd="",
                agents=["alice"],
            )
            t._session_stores[sid] = existing
            try:
                lifecycle.attach_session_store_for_creature(svc, creature)
                # Reused — same store.
                assert lifecycle.stores_for(svc)[sid] is existing
                assert attached[0] is existing
            finally:
                existing.close()
        finally:
            await t.shutdown()


# ── start_terrarium ──────────────────────────────────────────


class TestStartTerrarium:
    async def test_neither_path_raises(self):
        engine = Terrarium()
        svc = LocalTerrariumService(engine)
        try:
            with pytest.raises(ValueError):
                await lifecycle.start_terrarium(svc)
        finally:
            await engine.shutdown()

    async def test_with_config(self, tmp_path, monkeypatch):
        engine = Terrarium()
        svc = LocalTerrariumService(engine)
        from kohakuterrarium.terrarium.config import TerrariumConfig

        cfg = TerrariumConfig(name="test-terra", creatures=[], channels=[])
        seen_apply_kwargs: dict = {}

        async def _apply(c, pwd=None, llm=None, strict=True, session=None):
            seen_apply_kwargs.update(strict=strict, session=session)
            return SimpleNamespace(graph_id="g-new", creature_ids=set())

        engine.apply_recipe = _apply
        engine.attach_session = AsyncMock()
        engine.list_graphs = lambda: [
            SimpleNamespace(graph_id="g-new", creature_ids=set())
        ]
        engine._environments = {}
        monkeypatch.setattr(lifecycle, "_session_dir", lambda: str(tmp_path))
        try:
            sess = await lifecycle.start_terrarium(svc, config=cfg)
            assert sess.session_id == "g-new"
            assert sess.name == "test-terra"
            # Studio mints its own (richer-meta) store right after the
            # recipe applies — engine autosession MUST stay off for
            # this call or the same ``<gid>.kohakutr`` gets a second
            # live handle (leak; Windows file lock on saved delete).
            assert seen_apply_kwargs["session"] is False
        finally:
            await engine.shutdown()

    async def test_autosession_engine_single_store_handle(self, tmp_path, monkeypatch):
        # REGRESSION PIN: on an autosession engine
        # (``Terrarium(session_dir=...)`` — every API-server engine) a
        # Studio terrarium spawn must produce exactly ONE live store
        # handle: the Studio-minted one.  The engine-autosession path
        # minting a sibling handle at the same path leaked it forever —
        # on Windows the lingering SQLite handle locked the file, so
        # deleting the saved session after stop failed with WinError 32.
        from kohakuterrarium.terrarium.config import TerrariumConfig

        session_dir = tmp_path / "sessions"
        session_dir.mkdir()
        monkeypatch.setenv("KT_SESSION_DIR", str(session_dir))
        engine = Terrarium(session_dir=str(session_dir))
        svc = LocalTerrariumService(engine)
        cfg = TerrariumConfig(name="solo-terra", creatures=[], channels=[])
        try:
            sess = await lifecycle.start_terrarium(svc, config=cfg)
            sid = sess.session_id
            # One store file, owned by Studio — the engine minted (and
            # therefore owns) nothing.
            files = list(session_dir.glob("*.kohakutr"))
            assert [f.name for f in files] == [f"{sid}.kohakutr"]
            assert engine._owned_sessions == set()
            store = lifecycle.get_session_store(svc, sid)
            assert store is not None
            assert engine._session_stores[sid] is store
            # Stop closes the single handle; the file is then deletable
            # (on Windows a leaked second handle makes this raise).
            await lifecycle.stop_session(svc, sid)
            files[0].unlink()
        finally:
            await engine.shutdown()

    async def test_runtime_group_stop_and_resume_round_trip(
        self, tmp_path, monkeypatch
    ):
        from kohakuterrarium.session.store import SessionStore
        from kohakuterrarium.studio.persistence.session_index.reconcile import (
            read_entry_from_disk,
        )
        from kohakuterrarium.terrarium.creature_ops import wire_creature_on_engine

        session_dir = tmp_path / "sessions"
        root_cfg = tmp_path / "root-config"
        worker_cfg = tmp_path / "worker-config"
        root_pwd = tmp_path / "root-workspace"
        worker_pwd = tmp_path / "worker-workspace"
        for path in (root_cfg, worker_cfg, root_pwd, worker_pwd):
            path.mkdir()
        root_cfg.joinpath("config.yaml").write_text(
            "name: root\ninput:\n  type: none\noutput:\n  type: none\n",
            encoding="utf-8",
        )
        worker_cfg.joinpath("config.yaml").write_text(
            "name: worker\ninput:\n  type: none\noutput:\n  type: none\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("KT_SESSION_DIR", str(session_dir))

        engine = Terrarium(session_dir=str(session_dir))
        service = LocalTerrariumService(engine)
        resumed = None
        try:
            session = await lifecycle.start_creature(
                service,
                config_path=str(root_cfg),
                pwd=str(root_pwd),
                name="root",
            )
            sid = session.session_id
            root = engine.get_creature(session.creatures[0]["creature_id"])
            worker = await engine.add_creature(
                str(worker_cfg),
                graph=sid,
                pwd=str(worker_pwd),
                name="worker",
                parent_creature_id=root.creature_id,
                io="none",
                strict=False,
            )
            lifecycle.attach_session_store_for_creature(
                service, worker, config_path=str(worker_cfg)
            )
            await engine.add_channel(sid, "tasks")
            wire_creature_on_engine(engine, sid, root.creature_id, "tasks", "send")
            wire_creature_on_engine(engine, sid, worker.creature_id, "tasks", "listen")
            await engine.wire_output(
                root.creature_id, {"to": "worker", "with_content": True}
            )
            store_path = Path(lifecycle.get_session_store(service, sid).path)
            original_ids = {root.creature_id, worker.creature_id}

            await lifecycle.stop_session(service, sid)

            assert not engine.list_graphs()
            assert engine._session_stores == {}
            assert [p.name for p in session_dir.glob("*.kohakutr")] == [store_path.name]
            store = SessionStore.open_readonly(store_path)
            try:
                meta = store.load_meta()
                assert meta["status"] == "paused"
                assert {item["name"] for item in meta["runtime_creatures"]} == {
                    "root",
                    "worker",
                }
            finally:
                store.close()
            entry = read_entry_from_disk(store_path)
            assert entry is not None
            assert entry.status == "paused"

            resumed = await Terrarium.resume(str(store_path))
            creatures = {
                creature.name: creature for creature in resumed.list_creatures()
            }
            assert set(creatures) == {"root", "worker"}
            assert {
                creature.creature_id for creature in creatures.values()
            } == original_ids
            assert creatures["root"].is_privileged is True
            assert creatures["worker"].parent_creature_id == root.creature_id
            assert Path(creatures["root"].agent.executor._working_dir) == root_pwd
            assert Path(creatures["worker"].agent.executor._working_dir) == worker_pwd
            graph = resumed.get_graph(creatures["root"].graph_id)
            assert "tasks" in graph.channels
            assert graph.send_edges[creatures["root"].creature_id] == {"tasks"}
            assert graph.listen_edges[creatures["worker"].creature_id] == {"tasks"}
            assert (
                resumed.list_output_wiring(creatures["root"].creature_id)[0]["to"]
                == "worker"
            )
        finally:
            if resumed is not None:
                await resumed.shutdown()
            await engine.shutdown()


# ── list_sessions / get_session / find_creature ──────────────


class TestListGetSession:
    async def test_list_sessions_local(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            out = lifecycle.list_sessions(svc)
            assert len(out) == 1
            assert out[0].node_id == "_host"
        finally:
            await t.shutdown()

    async def test_list_sessions_remote_from_meta(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            lifecycle.meta_for(svc)["remote-sid"] = {
                "name": "remote-sess",
                "on_node": "worker-1",
            }
            out = lifecycle.list_sessions(svc)
            assert any(s.session_id == "remote-sid" for s in out)
        finally:
            await t.shutdown()

    async def test_get_session_local_path(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            sess = lifecycle.get_session(svc, gid)
            assert sess.session_id == gid
        finally:
            await t.shutdown()

    async def test_get_session_remote_meta(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            lifecycle.meta_for(svc)["sid-r"] = {
                "name": "rs",
                "on_node": "worker-1",
                "creature_id": "cid-r",
            }
            sess = lifecycle.get_session(svc, "sid-r")
            assert sess.home_node == "worker-1"
        finally:
            await t.shutdown()

    async def test_get_session_unknown_raises(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            with pytest.raises(KeyError):
                lifecycle.get_session(svc, "ghost")
        finally:
            await t.shutdown()


# ── _apply_creature_name ─────────────────────────────────────


class TestApplyCreatureName:
    async def test_renames_executor_trigger_compact(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        try:
            c = t.get_creature("alice")
            c.agent.executor = SimpleNamespace(_agent_name="alice")
            c.agent.trigger_manager._agent_name = "alice"
            c.agent.compact_manager = SimpleNamespace(_agent_name="alice")
            lifecycle._apply_creature_name(c, "renamed")
            assert c.name == "renamed"
            assert c.agent.executor._agent_name == "renamed"
            assert c.agent.trigger_manager._agent_name == "renamed"
            assert c.agent.compact_manager._agent_name == "renamed"
        finally:
            await t.shutdown()


# ── rename_session / rename_creature ─────────────────────────


class TestRename:
    async def test_rename_session_empty_raises(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            with pytest.raises(ValueError):
                lifecycle.rename_session(svc, "any", "")
        finally:
            await t.shutdown()

    async def test_rename_session_unknown_raises(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            with pytest.raises(KeyError):
                lifecycle.rename_session(svc, "ghost", "name")
        finally:
            await t.shutdown()

    async def test_rename_session_single_creature_renames(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            sess = lifecycle.rename_session(svc, gid, "Renamed")
            assert sess.name == "Renamed"
        finally:
            await t.shutdown()

    async def test_rename_creature_empty_raises(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            with pytest.raises(ValueError):
                lifecycle.rename_creature(svc, "alice", "")
        finally:
            await t.shutdown()

    async def test_rename_creature_updates_meta_when_solo(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            lifecycle.meta_for(svc)[gid] = {"name": "old"}
            lifecycle.rename_creature(svc, "alice", "new")
            assert lifecycle.meta_for(svc)[gid]["name"] == "new"
        finally:
            await t.shutdown()


# ── stop_session ─────────────────────────────────────────────


class TestStopSession:
    async def test_local_path(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            await lifecycle.stop_session(svc, gid)
            assert gid not in lifecycle.meta_for(svc)
        finally:
            await t.shutdown()

    async def test_remote_path(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        # Add a fake remote_creature method.
        svc.remove_creature = AsyncMock()
        try:
            lifecycle.meta_for(svc)["sid-r"] = {
                "on_node": "worker-1",
                "creature_id": "cid-r",
            }
            await lifecycle.stop_session(svc, "sid-r")
            svc.remove_creature.assert_awaited_with("cid-r")
            assert "sid-r" not in lifecycle.meta_for(svc)
        finally:
            await t.shutdown()

    async def test_unknown_raises(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            with pytest.raises(KeyError):
                await lifecycle.stop_session(svc, "ghost")
        finally:
            await t.shutdown()


# ── add_creature / list_creatures / remove_creature ──────────


class TestHotPlug:
    async def test_add_creature_unknown_session(self):
        from kohakuterrarium.terrarium.config import CreatureConfig

        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            cfg = CreatureConfig(
                name="x", config_data={"name": "x"}, base_dir=Path(".")
            )
            with pytest.raises(KeyError):
                await lifecycle.add_creature(svc, "ghost", cfg)
        finally:
            await t.shutdown()

    async def test_list_creatures_local(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            out = lifecycle.list_creatures(svc, gid)
            assert any(c["name"] == "alice" for c in out)
        finally:
            await t.shutdown()

    async def test_list_creatures_remote_fallback(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            lifecycle.meta_for(svc)["sid-r"] = {
                "name": "n",
                "on_node": "worker-1",
                "creature_id": "cid-r",
            }
            out = lifecycle.list_creatures(svc, "sid-r")
            assert out[0]["home_node"] == "worker-1"
        finally:
            await t.shutdown()

    async def test_list_creatures_unknown_raises(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            with pytest.raises(KeyError):
                lifecycle.list_creatures(svc, "ghost")
        finally:
            await t.shutdown()

    async def test_remove_creature_unknown_session_raises(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            with pytest.raises(KeyError):
                await lifecycle.remove_creature(svc, "ghost", "cid")
        finally:
            await t.shutdown()

    async def test_remove_creature_unknown_creature_returns_false(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            out = await lifecycle.remove_creature(svc, gid, "ghost")
            assert out is False
        finally:
            await t.shutdown()

    async def test_remove_creature_success(self):
        t = await (
            TestTerrariumBuilder().with_creature("alice").with_creature("bob").build()
        )
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            out = await lifecycle.remove_creature(svc, gid, "alice")
            assert out is True
        finally:
            await t.shutdown()


# ── find_creature ───────────────────────────────────────────


class TestFindCreature:
    async def test_by_id(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            c = lifecycle.find_creature(svc, gid, "alice")
            assert c.creature_id == "alice"
        finally:
            await t.shutdown()

    async def test_by_name(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            # Lookup by exact display name resolves the same creature.
            c = lifecycle.find_creature(svc, gid, "alice")
            assert c is t.get_creature("alice")
        finally:
            await t.shutdown()

    async def test_underscore_session(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            # "_" wildcard session id still resolves the creature.
            c = lifecycle.find_creature(svc, "_", "alice")
            assert c is t.get_creature("alice")
        finally:
            await t.shutdown()

    async def test_root_alias(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            alice = t.get_creature("alice")
            alice.is_privileged = True
            alice.name = "root"
            c = lifecycle.find_creature(svc, gid, "root")
            assert c is alice
        finally:
            await t.shutdown()

    async def test_unknown_raises(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = t.get_creature("alice").graph_id
            with pytest.raises(KeyError):
                lifecycle.find_creature(svc, gid, "ghost")
        finally:
            await t.shutdown()


# ── find_session_for_creature ───────────────────────────────


class TestFindSessionForCreature:
    async def test_found(self):
        t = await TestTerrariumBuilder().with_creature("alice").build()
        svc = LocalTerrariumService(t)
        try:
            gid = await lifecycle.find_session_for_creature(svc, "alice")
            assert gid == t.get_creature("alice").graph_id
        finally:
            await t.shutdown()

    async def test_unknown_returns_none(self):
        t = await TestTerrariumBuilder().build()
        svc = LocalTerrariumService(t)
        try:
            assert await lifecycle.find_session_for_creature(svc, "ghost") is None
        finally:
            await t.shutdown()
