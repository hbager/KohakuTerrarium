---
name: plan
description: Implementation planning sub-agent
category: subagent
tags: [planning, architecture, design]
---

# plan

Sub-agent for creating implementation plans and design decisions.

## WHEN TO USE

- Need to plan a new feature implementation
- Designing changes that affect multiple files
- Want to think through architecture before coding
- Complex refactoring that needs a strategy

## WHEN NOT TO USE

- Simple, obvious changes
- You already know exactly what to do
- Quick fixes or small edits

## HOW TO USE

```xml
<agent type="plan">task description</agent>
```

## Arguments

| Arg | Type | Description |
|-----|------|-------------|
| type | attribute | Must be "plan" |
| body | content | What needs to be planned/designed |

## Examples

```xml
<!-- Feature planning -->
<agent type="plan">Plan implementation for user authentication with JWT</agent>

<!-- Refactoring strategy -->
<agent type="plan">Plan refactoring the database layer to use async</agent>

<!-- Architecture decision -->
<agent type="plan">Design the caching strategy for API responses</agent>

<!-- Migration planning -->
<agent type="plan">Plan migration from REST to GraphQL</agent>
```

## CAPABILITIES

The plan sub-agent has access to:
- `glob` - Find relevant files
- `grep` - Search for patterns
- `read` - Examine existing code

It will:
1. Explore relevant existing code
2. Identify affected files/modules
3. Consider trade-offs
4. Create step-by-step plan

## OUTPUT

Returns a structured plan including:
- Overview of approach
- Files to create/modify
- Step-by-step implementation order
- Potential issues/considerations

## LIMITATIONS

- Read-only (creates plan, doesn't implement)
- Based on current codebase state
- May need refinement based on your specific requirements
