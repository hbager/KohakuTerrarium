---
name: grep
description: Search file contents for a pattern (regex)
category: builtin
tags: [search, content]
---

# grep

Search file contents for a pattern using regex.

## WHEN TO USE

- Finding where something is defined/used
- Searching for specific code patterns
- Locating TODOs, FIXMEs, or comments
- Finding function/class definitions

## HOW TO USE

```xml
<grep>pattern</grep>

<!-- With optional parameters -->
<grep path="src/" glob="**/*.py" limit="50" ignore_case="true">pattern</grep>
```

## Arguments

| Arg | Type | Description |
|-----|------|-------------|
| pattern | body | Regex pattern to search (required) |
| path | attribute | Directory to search (default: cwd) |
| glob | attribute | File pattern filter (default: `**/*`) |
| limit | attribute | Max matches (default: 50) |
| ignore_case | attribute | Case-insensitive (default: false) |

## Examples

```xml
<!-- Find function definitions -->
<grep glob="**/*.py">def \w+\(</grep>

<!-- Case-insensitive search -->
<grep ignore_case="true">todo|fixme</grep>

<!-- Search specific directory -->
<grep path="src/components" glob="*.tsx">import.*react</grep>

<!-- Search in single file -->
<grep path="src/main.py">import</grep>
```

## Output Format

```
src/main.py:10: def main():
src/utils.py:25: def helper(x):

(2 matches in 15 files)
```

## LIMITATIONS

- Regex syntax (escape special chars with `\`)
- Large codebases may need file filter

## TIPS

- Use `glob` arg to narrow file types
- Escape regex special chars: `\(`, `\[`, `\.`
- Use `read` after grep to examine context
- For simple text, `ignore_case="true"` helps
