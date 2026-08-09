"""Engine-level resume — adopt a saved session into a live engine.

Body of :meth:`Terrarium.resume` and :meth:`Terrarium.adopt_session`,
kept in a sibling module so ``engine.py`` stays under the file-size
cap.  Exactly the same pattern as ``terrarium/root.py`` for
``assign_root``.

Resume is an engine concern: rebuild creatures from saved config,
inject the saved conversation / scratchpad / triggers / events, wrap
each agent in a :class:`Creature`, attach the :class:`SessionStore`
at the graph level, and start everything.  The Studio tier sits on
top of this and only adds metadata bookkeeping (``_meta`` /
``_session_stores`` in :mod:`studio.sessions.lifecycle`) plus the
HTTP / CLI orchestration.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kohakuterrarium.errors import SessionNotResumableError
from kohakuterrarium.builtins.inputs.none import NoneInput
from kohakuterrarium.session.resume import (
    _open_store_with_migration,
    _rebuild_agent,
    detect_session_type,
    inject_saved_state,
    resume_agent,
)
from kohakuterrarium.session.store import SessionStore
from kohakuterrarium.terrarium.config import load_terrarium_config
from kohakuterrarium.terrarium.creature_host import Creature, _safe_creature_id
import kohakuterrarium.terrarium.topology_snapshot as _topo_snap
from kohakuterrarium.utils.logging import get_logger

if TYPE_CHECKING:
    from kohakuterrarium.terrarium.engine import Terrarium

logger = get_logger(__name__)


async def resume_into_engine(
    engine: "Terrarium",
    store: SessionStore | str | Path,
    *,
    pwd: str | None = None,
    llm: Any = None,
) -> str:
    """Adopt a saved session into ``engine``.  Returns the graph_id.

    Reads the saved store's metadata to dispatch between the agent
    and terrarium rebuild paths, wraps the rebuilt agent(s) in
    :class:`Creature` objects, adopts them via ``engine.add_creature``,
    and attaches the ``SessionStore`` at the graph level.

    ``store`` may be a path-like to a ``.kohakutr`` file or an
    already-open :class:`SessionStore` instance.  An instance is CLOSED
    here first — the rebuild paths open the file themselves, and two
    live handles on one session file kept independent event counters
    (E8).
    """
    path = _resolve_store_path(store)
    if isinstance(store, SessionStore):
        store.close(update_status=False)
    session_type = detect_session_type(path)

    if session_type == "agent":
        return await _resume_agent_into_engine(engine, path, pwd=pwd, llm=llm)
    if session_type == "terrarium":
        return await _resume_terrarium_into_engine(engine, path, pwd=pwd, llm=llm)
    raise SessionNotResumableError(f"Unknown saved-session type: {session_type!r}")


def _resolve_store_path(store: SessionStore | str | Path) -> Path:
    if isinstance(store, SessionStore):
        # SessionStore exposes ``path`` (set in __init__) — fall back
        # to ``str(store)`` only if the attribute is missing on a future
        # store implementation.
        return Path(getattr(store, "path", str(store)))
    return Path(str(store))


async def _cleanup_failed_resume(
    engine: "Terrarium", store: SessionStore, graph_ids: set[str]
) -> None:
    for graph_id in graph_ids:
        try:
            await engine.stop_graph(graph_id)
        except BaseException as exc:
            logger.warning(
                "Failed to stop partially resumed graph",
                graph_id=graph_id,
                error=str(exc),
                exc_info=True,
            )
        engine._owned_sessions.discard(graph_id)
        if engine._session_stores.get(graph_id) is store:
            engine._session_stores.pop(graph_id, None)
    try:
        store.close()
    except BaseException as exc:
        logger.warning(
            "Failed to close store after resume failure",
            error=str(exc),
            exc_info=True,
        )


async def _resume_agent_into_engine(
    engine: "Terrarium",
    path: Path,
    *,
    pwd: str | None,
    llm: Any,
) -> str:
    """Standalone-agent resume: rebuild Agent, wrap, adopt, attach.

    The rebuilt agent is adopted into a live engine and driven through
    the engine's wiring / attach WebSocket — never its config's own
    ``input: cli`` loop. ``input_module=NoneInput()`` suppresses that
    loop exactly as ``engine.add_creature(io="none")`` does for
    the Studio / Lab spawn path; without it a worker-side resume boots
    a stdin reader with no TTY and wedges the worker.
    """
    store = _open_store_with_migration(path, writer_lock=True)
    try:
        meta = store.load_meta()
    except BaseException:
        await _cleanup_failed_resume(engine, store, set())
        raise
    agents = list(meta.get("agents") or [])
    runtime_names = {
        item.get("name")
        for item in (meta.get("runtime_creatures") or [])
        if isinstance(item, dict) and item.get("name")
    }
    if len(agents) > 1 or (runtime_names and runtime_names == set(agents)):
        return await _resume_runtime_group_into_engine(
            engine, store, meta, pwd=pwd, llm=llm
        )
    store.close()

    # session.resume.resume_agent does the heavy lifting: opens store
    # with migration, rebuilds Agent from the saved config, injects
    # every state slot, and calls agent.attach_session_store(store).
    agent, store = resume_agent(
        path,
        pwd_override=pwd,
        io_mode=None,
        llm=llm,
        input_module=NoneInput(),
    )
    creature_obj = Creature(
        creature_id=_safe_creature_id(agent.config.name),
        name=agent.config.name,
        agent=agent,
        config=agent.config,
    )
    try:
        # ``session=False``: the SAVED store attaches below — autosession
        # minting a fresh sibling file here would orphan it on disk.
        creature = await engine.add_creature(creature_obj, start=True, session=False)

        # Attach at graph level. ``Agent.attach_session_store`` is
        # idempotent for the same store, so this updates graph bookkeeping
        # without adding a duplicate SessionOutput sink.
        await engine.attach_session(creature.graph_id, store)
        engine._owned_sessions.add(creature.graph_id)
    except BaseException:
        graph_ids = {creature_obj.graph_id} if creature_obj.graph_id else set()
        await _cleanup_failed_resume(engine, store, graph_ids)
        raise

    logger.info(
        "Agent session resumed into engine",
        session_id=creature.graph_id,
        creature_id=creature.creature_id,
        path=str(path),
    )
    return creature.graph_id


async def _resume_runtime_group_into_engine(
    engine: "Terrarium",
    store: SessionStore,
    meta: dict,
    *,
    pwd: str | None,
    llm: Any,
) -> str:
    created_graph_ids: set[str] = set()
    try:
        descriptors = list(meta.get("runtime_creatures") or [])
        if not descriptors:
            descriptors = [
                {
                    "name": name,
                    "config_path": meta.get("config_path", ""),
                    "config_snapshot": meta.get("config_snapshot") or {},
                    "pwd": meta.get("pwd", "."),
                }
                for name in list(meta.get("agents") or [])
            ]

        sid: str | None = None
        for descriptor in descriptors:
            agent_name = descriptor.get("name")
            config_path = descriptor.get("config_path", "")
            config_snapshot = descriptor.get("config_snapshot") or {}
            if not agent_name or not (config_path or config_snapshot):
                raise ValueError("Runtime creature has incomplete metadata")
            effective_pwd = pwd or descriptor.get("pwd") or meta.get("pwd", ".")
            if not (effective_pwd and os.path.isdir(effective_pwd)):
                effective_pwd = None
            agent = _rebuild_agent(
                config_path="" if config_snapshot else config_path,
                config_snapshot=config_snapshot,
                llm=llm,
                io_kwargs={"input_module": NoneInput()},
                pwd=effective_pwd,
            )
            inject_saved_state(agent, store, agent_name)
            creature_obj = Creature(
                creature_id=descriptor.get("creature_id")
                or _safe_creature_id(agent.config.name),
                name=agent_name,
                agent=agent,
                config=agent.config,
                is_privileged=bool(descriptor.get("is_privileged", False)),
                parent_creature_id=descriptor.get("parent_creature_id"),
            )
            try:
                creature = await engine.add_creature(
                    creature_obj,
                    graph=sid,
                    start=True,
                    session=False,
                )
            finally:
                if creature_obj.graph_id:
                    created_graph_ids.add(creature_obj.graph_id)
            sid = creature.graph_id

        if sid is None:
            raise ValueError("Session has no agents in metadata")
        await engine.attach_session(sid, store)
        engine._owned_sessions.add(sid)
        store.update_status("running")
        await _topo_snap.replay(engine, sid)
    except BaseException:
        await _cleanup_failed_resume(engine, store, created_graph_ids)
        raise

    logger.info(
        "Runtime group session resumed into engine",
        session_id=sid,
        path=str(store.path),
        creatures=len(descriptors),
    )
    return sid


async def _resume_terrarium_into_engine(
    engine: "Terrarium",
    path: Path,
    *,
    pwd: str | None,
    llm: Any = None,
) -> str:
    """Multi-creature recipe resume: rebuild graph, inject per-creature."""
    store = _open_store_with_migration(path, writer_lock=True)
    created_graph_ids: set[str] = set()
    try:
        graph_id = await _resume_terrarium_from_store(
            engine,
            store,
            path=path,
            pwd=pwd,
            llm=llm,
            created_graph_ids=created_graph_ids,
        )
        return graph_id
    except BaseException:
        await _cleanup_failed_resume(engine, store, created_graph_ids)
        raise


async def _resume_terrarium_from_store(
    engine: "Terrarium",
    store: SessionStore,
    *,
    path: Path,
    pwd: str | None,
    llm: Any,
    created_graph_ids: set[str],
) -> str:
    meta = store.load_meta()
    config_path = meta.get("config_path", "")
    if not config_path:
        raise SessionNotResumableError("Saved terrarium has no config_path in metadata")

    # ``pwd`` flows into ``apply_recipe`` (per-creature workspaces) —
    # no process-wide ``os.chdir`` (E8).
    pwd = pwd or meta.get("pwd", ".")
    if not (pwd and os.path.isdir(pwd)):
        pwd = None

    config = load_terrarium_config(config_path)

    # Build the topology via the engine — creates every creature,
    # wires channels, assigns root, and starts the agents.  Each agent
    # begins with an empty conversation; we inject the saved state
    # below.  Since input hasn't started flowing yet, injection lands
    # before any new turn begins.
    #
    # ``session=False``: the SAVED store attaches below.  Under
    # autosession (``Terrarium(session_dir=...)`` — every API-server
    # engine) ``apply_recipe`` would otherwise mint a fresh
    # ``<new_gid>.kohakutr`` that the saved-store attach immediately
    # orphans: an empty ghost file stuck at ``status="running"`` in
    # the saved-session list, plus a leaked open handle.  Mirrors the
    # ``session=False`` in ``_resume_agent_into_engine``.
    graph = await engine.apply_recipe(
        config,
        pwd=pwd,
        llm=llm,
        session=False,
        _on_graph_created=created_graph_ids.add,
    )
    sid = graph.graph_id
    created_graph_ids.add(sid)

    # Per-creature state injection.
    #
    # Resolve each rebuilt creature to its *saved* runtime name. Saved
    # events are keyed by ``<saved_name>:e:<id>``, but ``apply_recipe``
    # may have produced a creature whose current ``config.name`` does
    # not match that key (the fresh build can re-roll random suffixes,
    # or the saved recipe stored an explicit per-creature name that the
    # rebuild collapsed to the config default). Match in this order:
    #
    #   1. fresh name already exists in the saved agents list;
    #   2. otherwise consume the next unused saved name positionally.
    #
    # Without this we'd inject under the fresh name and recover zero
    # events. Same root cause as the creature-resume bug fixed in
    # ``session.resume.align_agent_name``.
    saved_agents = list(meta.get("agents") or [])
    saved_set = set(saved_agents)
    consumed: set[str] = set()
    for cid in graph.creature_ids:
        try:
            creature = engine.get_creature(cid)
        except KeyError:
            continue
        fresh = creature.agent.config.name
        if fresh in saved_set and fresh not in consumed:
            agent_name = fresh
        else:
            # Pull the next saved name we haven't consumed yet.
            agent_name = next(
                (n for n in saved_agents if n not in consumed),
                fresh,
            )
        consumed.add(agent_name)
        inject_saved_state(creature.agent, store, agent_name)
        # ``inject_saved_state`` aligns ``agent.config.name``; mirror
        # the saved name onto the Creature wrapper too so chat-history
        # lookups (which key off ``creature.name``) hit the same
        # namespace as the events we just injected.
        creature.name = agent_name
        if creature.config is not None:
            creature.config.name = agent_name
        creature.agent.attach_session_store(store)

    # Attach at graph level. Each creature was already attached just
    # above, but ``Agent.attach_session_store`` is idempotent for the
    # same store so this preserves graph/session bookkeeping safely.
    await engine.attach_session(sid, store)
    engine._owned_sessions.add(sid)
    store.update_status("running")

    # Replay runtime topology mutations on top of the recipe-rebuilt
    # graph: any channel the user added via ``service.add_channel`` /
    # any wire from ``service.connect`` after the original spawn lives
    # in ``meta["runtime_topology"]`` (written by every engine topology
    # method). Without this replay, those user-added channels + wires
    # are lost on every resume.
    await _topo_snap.replay(engine, sid)

    logger.info(
        "Terrarium session resumed into engine",
        session_id=sid,
        path=str(path),
        creatures=len(graph.creature_ids),
    )
    return sid
