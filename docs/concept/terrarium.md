# Terrarium - The Wiring Layer

## The Idea

Most multi-agent frameworks force you to choose: either everything is hierarchical (one boss, many workers) or everything is peer-to-peer (everyone equal). Both break down at scale.

KohakuTerrarium says: **use both, at different levels.**

```
    Vertical (inside a creature)       Horizontal (between creatures)

         Controller                  brainstorm <---> planner
         /       \                        |              |
    sub-agent  sub-agent              channels        channels
                                          |              |
    Hierarchical delegation           writer <-----> reviewer
    for task decomposition
                                     Peer collaboration
                                     for multi-role teams
```

The **creature** handles the vertical. The **terrarium** handles the horizontal. The boundary is clean: a creature does not know it is in a terrarium.

## What a Terrarium Does

A terrarium is **not** an agent. It has no LLM, no decision-making, no intelligence. It is pure wiring:

1. **Loads** standalone creature configs (unchanged from their solo use)
2. **Creates channels** connecting creatures
3. **Injects triggers** so creatures react to incoming channel messages
4. **Injects topology** into each creature's system prompt ("you can send to X, you receive from Y")
5. **Manages lifecycle** (start, stop, monitor)
6. **Provides an API** for external interaction

## The Opacity Principle

Creatures are opaque. The terrarium cannot inspect or modify their internals.

```
+-------------+     +-------------------+     +-----------------+
|  Creatures  |     |  Terrarium Layer  |     | Human Interface |
|  (opaque)   |<--->|  (wiring)         |<--->| (pluggable)     |
|             |     |                   |     |                 |
| Has:        |     | Has:              |     | Has:            |
| - LLM       |     | - Channels        |     | - CLI           |
| - Tools     |     | - Triggers        |     | - HTTP API      |
| - Sub-agents|     | - Lifecycle       |     | - Web UI        |
| - Memory    |     | - Prompt injection|     | - nothing       |
+-------------+     +-------------------+     +-----------------+
```

This mirrors the microservice pattern:
- Creature = microservice (private internals, external interface)
- Terrarium = service mesh (routing, lifecycle, no business logic)
- Channels = message queues

## Communication Model

Creatures communicate **explicitly** through channels. The terrarium never silently pipes creature output into channels.

**Receiving**: The terrarium injects `ChannelTrigger`s. Messages arrive automatically as events. The creature does not poll or call `wait_channel`.

**Sending**: The creature calls `send_message` when its workflow requires it. The LLM decides what to share.

```
brainstorm creature:
  1. Receives seed prompt (via trigger)
  2. Thinks, generates ideas
  3. Sends best idea to "ideas" channel  <-- explicit decision

planner creature:
  1. Receives idea (via trigger, automatic)
  2. Plans chapter outlines
  3. Sends each outline to "outline" channel  <-- explicit decision
```

## Topologies

Different wiring patterns emerge from channel configuration:

```
Pipeline:                    Hub-and-spoke:
  A --> [ch] --> B --> [ch]      architect --> [tasks] --> worker_1
       --> C                     architect --> [tasks] --> worker_2
                                 worker_* --> [results] --> architect

Group chat:                  Hybrid:
  A --+                         A --> [queue] --> B
  B --+--> [broadcast] --> all  all <--> [broadcast] <--> all
  C --+
```

All topologies are just channel configuration - no code changes needed.

## Defining a Terrarium

```yaml
terrarium:
  name: novel_writer
  creatures:
    - name: brainstorm
      config: ./creatures/brainstorm/
      channels:
        listen: [seed, team_chat]
        can_send: [ideas, team_chat]
    - name: planner
      config: ./creatures/planner/
      channels:
        listen: [ideas, team_chat]
        can_send: [outline, team_chat]
  channels:
    seed:      { type: queue, description: "User prompt" }
    ideas:     { type: queue, description: "Story concepts" }
    outline:   { type: queue, description: "Chapter outlines" }
    team_chat: { type: broadcast, description: "Shared context" }
```

Creatures point to standalone agent configs. The terrarium adds the wiring. The creature configs do not change.

## The Root Agent

A terrarium can optionally declare a `root:` section. This is an inline agent config (same format as any creature config) that sits **outside** the terrarium:

```yaml
terrarium:
  name: swe_team

  root:
    base_config: creatures/root
    controller:
      model: gpt-5.4
      auth_mode: codex-oauth
      tool_format: native
    input:
      type: tui
    output:
      type: tui
      controller_direct: true

  creatures:
    - name: swe
      base_config: creatures/swe
      channels:
        listen: [tasks]
        can_send: [results]
```

The root agent is NOT a creature inside the terrarium. It does not participate in channels and the terrarium does not inject triggers or topology into it. Instead, the root agent uses terrarium management tools to control the terrarium from the outside:

- `terrarium_send` -- inject messages into channels (dispatch tasks)
- `terrarium_observe` -- watch a channel for results (runs in background)
- `terrarium_status` -- check terrarium and creature status
- `creature_start` / `creature_stop` -- hot-plug creatures

The root agent is force-given all 7 terrarium tools regardless of its creature config. It is typically built on the `root` creature, which inherits general capabilities.

The root config uses the same inheritance system as any other agent config (`base_config`, controller overrides, I/O overrides). The user talks to the root agent; the root agent orchestrates the team.

See [Configuration Reference](../guide/configuration.md) for all fields. See [Channels](channels.md) for channel types and semantics.
