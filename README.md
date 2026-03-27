# KohakuTerrarium

**A universal agent framework for building fully autonomous systems.**

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)
![asyncio](https://img.shields.io/badge/runtime-asyncio-purple)

---

KohakuTerrarium is a Python framework for building any kind of agent -- coding assistants, conversational AI, monitoring drones, multi-agent swarms. Define your agent in YAML, pick tools and sub-agents, and let the framework handle orchestration, streaming, and coordination.

## Key Features

- **Any agent type** -- SWE agents, chatbots, autonomous monitors, multi-agent coordinators
- **Async-first execution** -- tools start during LLM streaming, run in parallel via `asyncio`
- **Nested sub-agents** -- full agents with their own LLM, tools, and lifecycle
- **Channel-based coordination** -- async named message queues for cross-agent communication
- **YAML-driven config** -- define agents declaratively, minimal code required
- **Streaming parser** -- real-time `[/tool]...[tool/]` detection via state machine
- **Folder-based memory** -- persistent read/write files, no external database needed
- **Session scratchpad** -- structured key-value working memory, auto-injected into context
- **Trigger system** -- timers, channel events, and composites for autonomous operation
- **On-demand docs** -- full tool documentation loaded only when the LLM requests it

## Quick Start

```bash
git clone https://github.com/KohakuBlueLeaf/KohakuTerrarium.git
cd KohakuTerrarium
uv pip install -e .

export OPENROUTER_API_KEY=your_key_here

python -m kohakuterrarium.run agents/swe_agent
```

## How It Works

```
Input ──────┐
            +----> Controller (LLM) <----> Tools (parallel, non-blocking)
Trigger ────┘           |            <----> Sub-Agents (nested LLMs)
                        |
                  +-----+------+
                  |            |
               Output      Channels ----> Other Agents
```

Five systems, one event loop:

| System | Role |
|--------|------|
| **Input** | User requests, chat messages, ASR streams |
| **Trigger** | Timers, channel events -- for autonomous operation |
| **Controller** | LLM orchestrator -- dispatches tasks, makes decisions |
| **Tool Calling** | Background parallel execution of tools and sub-agents |
| **Output** | Streaming to stdout, files, TTS, APIs, webhooks |

The controller's job is to dispatch, not to do heavy work. Long outputs come from specialized sub-agents. This keeps the controller lightweight and context small.

## Built-in Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands |
| `python` | Run Python scripts |
| `read` | Read file contents |
| `write` | Create or overwrite files |
| `edit` | Modify files with search-replace |
| `glob` | Find files by pattern |
| `grep` | Search file contents with regex |
| `tree` | Display directory structure |
| `think` | Extended reasoning (no side effects) |
| `scratchpad` | Session-scoped key-value working memory |
| `send_message` | Send message to a named channel |
| `wait_channel` | Wait for a message on a named channel |
| `http` | Make HTTP requests |
| `ask_user` | Prompt the user for clarification |
| `json_read` | Read and query JSON files |
| `json_write` | Write structured JSON data |

## Built-in Sub-Agents

| Sub-Agent | Purpose | Access |
|-----------|---------|--------|
| `explore` | Search and explore codebase | read-only |
| `plan` | Create implementation plans | read-only |
| `worker` | Implement code changes, fix bugs, refactor | read-write |
| `critic` | Review and critique code, plans, or outputs | no tools |
| `summarize` | Condense long content into concise summaries | no tools |
| `research` | Research topics using files and web access | read-only |
| `coordinator` | Coordinate multiple agents via channels | channels only |
| `memory_read` | Search and retrieve from memory | read-only |
| `memory_write` | Store information to memory | read-write |
| `response` | Generate user-facing responses | output sub-agent |

## Example Agents

### SWE Agent

A software engineering assistant -- the Claude Code / Codex pattern. Direct controller output with code exploration, planning, and execution sub-agents.

```yaml
name: swe_agent
tools: [bash, python, read, write, edit, glob, grep, think, scratchpad, ask_user]
subagents: [explore, plan, worker, critic, summarize]
termination:
  max_turns: 100
  keywords: ["TASK_COMPLETE"]
```

### Multi-Agent Coordinator

Dispatches research and worker sub-agents via channels, combining results for complex tasks.

```yaml
name: multi_agent
tools: [send_message, wait_channel, scratchpad, think, read, write, edit,
        bash, glob, grep, http]
subagents: [explore, research, worker, coordinator, summarize, critic]
termination:
  max_turns: 30
  keywords: ["ALL_TASKS_COMPLETE"]
```

### Planner Agent

Plan-and-execute with scratchpad-driven planning, worker execution, and critic review loops.

```yaml
name: planner_agent
tools: [read, write, edit, bash, glob, grep, scratchpad, think]
subagents: [plan, worker, critic, summarize]
termination:
  max_turns: 50
  keywords: ["ALL_STEPS_COMPLETE"]
```

### Monitor Agent

Trigger-driven autonomous agent with no user input. Runs health checks on timers and responds to channel alerts.

```yaml
name: monitor_agent
input: { type: none }
triggers:
  - type: timer
    interval: 60
    prompt: "Run health check"
  - type: channel
    channel: monitor_alerts
    prompt: "Investigate this alert: {content}"
tools: [bash, http, read, scratchpad, send_message, think]
subagents: [explore, summarize]
```

### Conversational Agent

Streaming conversational AI with Whisper ASR input, interactive output sub-agent, and TTS output.

```yaml
name: conversational
input: { type: whisper, model: small, device: cuda }
tools: [read, write, think, scratchpad]
subagents: [memory_read, memory_write, research, critic, output]
output: { type: custom, controller_direct: false }
```

### Discord Bot

Group chat bot with ephemeral context, named outputs, and custom tools.

```yaml
name: discord_bot
input: { type: custom, module: ./custom/discord_io.py }
output:
  named_outputs:
    discord: { type: custom, module: ./custom/discord_io.py }
tools: [tree, read, write, edit, glob, grep]
subagents: [memory_read, memory_write]
```

### RP Agent

Roleplay chatbot with persistent character memory and output sub-agent pattern.

```yaml
name: rp_agent
tools: [tree, read, write, edit, grep, glob]
subagents: [memory_read, memory_write, output]
memory:
  init_files: [character.md, rules.md]
  writable_files: [context.md, facts.md, preferences.md]
```

## Multi-Agent Patterns

### Parallel Dispatch

The controller dispatches multiple sub-agents simultaneously, then waits for their results through channels:

```
[/research]Investigate auth patterns[research/]
[/worker]Scaffold the module[worker/]
[/wait_channel]@@channel=results[wait_channel/]
```

### Plan-Execute-Review

Scratchpad-driven loop: plan steps, execute each with a worker, validate with a critic, iterate:

```
[/plan]Design migration strategy[plan/]
[/worker]Execute step 1[worker/]
[/critic]Review step 1 against the plan[critic/]
```

### Trigger-Driven Autonomous

No user input. Timers and channel triggers drive the agent entirely:

```yaml
input: { type: none }
triggers:
  - type: timer
    interval: 60
    prompt: "Run health check"
  - type: channel
    channel: monitor_alerts
    prompt: "Investigate this alert: {content}"
```

## Configuration

A complete agent configuration with all sections:

```yaml
name: my_agent
version: "1.0"

# LLM -- supports any OpenAI-compatible provider
controller:
  model: "google/gemini-3-flash-preview"
  temperature: 0.7
  max_tokens: 512000
  api_key_env: OPENROUTER_API_KEY
  base_url: https://openrouter.ai/api/v1

# System prompt loaded from Markdown with Jinja2 templating
system_prompt_file: prompts/system.md

# Input source (cli, whisper, custom, or none for trigger-only)
input:
  type: cli
  prompt: "You: "

# Triggers for autonomous operation (optional)
triggers:
  - type: timer
    interval: 300
    prompt: "Check for updates"

# Tools -- pick from 16 builtins or add custom
tools:
  - name: bash
    type: builtin
  - name: read
    type: builtin
  - name: write
    type: builtin

# Sub-agents -- pick from 10 builtins or add custom
subagents:
  - name: explore
    type: builtin
    extra_prompt: "Focus on Python files."
  - name: worker
    type: builtin

# When to stop
termination:
  max_turns: 50
  keywords: ["TASK_COMPLETE"]

# Output routing
output:
  type: stdout
  controller_direct: true
```

## Tool Call Format

KohakuTerrarium uses a bracket-based format that works with any LLM:

```
[/bash]ls -la[bash/]

[/read]@@path=src/main.py[read/]

[/write]
@@path=hello.py
print("Hello, World!")
[write/]

[/edit]
@@path=config.py
@@old=debug = False
@@new=debug = True
[edit/]

[/explore]Find all API endpoints[explore/]

[/info]bash[info/]
```

## Project Structure

```
src/kohakuterrarium/
+-- core/            # Runtime: agent, controller, executor, events, channels
+-- modules/         # Protocols: input, trigger, tool, output, subagent
+-- builtins/        # 16 tools, 10 sub-agents, CLI/Whisper input, stdout/TTS output
+-- parsing/         # Stream parser: state machine for [/tool] block detection
+-- prompt/          # System prompt aggregation + Jinja2 templating
+-- llm/             # LLM abstraction (OpenAI/OpenRouter)
+-- utils/           # Structured colored logging

agents/              # Example agent configurations (7 included)
docs/                # Architecture docs, API reference, guides
```

## Documentation

- [Architecture Overview](docs/architecture.md)
- [API Reference](docs/api/)
- [Usage Guides](docs/guides/)
- [Code Conventions](CLAUDE.md)

## Contributing

Contributions welcome. Read [CLAUDE.md](CLAUDE.md) for code conventions, architecture guidelines, and logging standards.

## License

Apache-2.0
