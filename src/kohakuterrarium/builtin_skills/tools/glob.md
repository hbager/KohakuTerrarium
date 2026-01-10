---
name: glob
description: Find files matching a glob pattern
category: builtin
tags: [file, search]
---

# glob

Find files matching a glob pattern.

## Arguments

- `pattern` (required): Glob pattern to match (e.g., `**/*.py`, `src/*.js`)
- `path` (optional): Base directory to search in (default: current directory)
- `limit` (optional): Maximum number of results (default: 100)

## Examples

Find all Python files:
```
##tool##
name: glob
args:
  pattern: "**/*.py"
##tool##
```

Find files in specific directory:
```
##tool##
name: glob
args:
  pattern: "*.ts"
  path: src/components
##tool##
```

## Pattern Syntax

- `*` - matches any characters except path separator
- `**` - matches any characters including path separators (recursive)
- `?` - matches single character
- `[abc]` - matches a, b, or c

## Output Format

Returns list of matching file paths (newest first):
```
src/main.py
src/utils/helpers.py
tests/test_main.py
```
