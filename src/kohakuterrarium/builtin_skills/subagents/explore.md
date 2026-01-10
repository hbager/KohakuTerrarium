---
name: explore
description: Autonomous codebase exploration sub-agent
category: subagent
tags: [search, exploration, analysis]
---

# explore

Autonomous sub-agent for codebase exploration and analysis.

## WHEN TO USE

- You don't know where relevant code is located
- Need to understand how something works across multiple files
- Complex search requiring multiple glob/grep/read operations
- Answering questions like "how does X work?" or "find all Y"

## WHEN NOT TO USE

- You already know the exact file to read
- Simple single-file operations
- Quick pattern match (use grep directly)

## HOW TO USE

```xml
<agent type="explore">task description</agent>
```

## Arguments

| Arg | Type | Description |
|-----|------|-------------|
| type | attribute | Must be "explore" |
| body | content | Task description (what to find/understand) |

## Examples

```xml
<!-- Find related code -->
<agent type="explore">Find all files related to authentication</agent>

<!-- Understand architecture -->
<agent type="explore">How does the config loading system work?</agent>

<!-- Locate specific patterns -->
<agent type="explore">Find where user permissions are checked</agent>

<!-- Analyze dependencies -->
<agent type="explore">What modules import the database module?</agent>
```

## CAPABILITIES

The explore sub-agent has access to:
- `glob` - Find files by pattern
- `grep` - Search file contents
- `read` - Read file contents

It will autonomously:
1. Search for relevant files
2. Read and analyze contents
3. Follow imports/references
4. Return a summary of findings

## OUTPUT

Returns a summary of what was found, including:
- Relevant files discovered
- Key code sections
- How components connect

## LIMITATIONS

- Read-only (cannot modify files)
- Limited turns (may not explore everything)
- Returns text summary (not structured data)
