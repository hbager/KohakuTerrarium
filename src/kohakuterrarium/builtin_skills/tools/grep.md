---
name: grep
description: Search file contents for a pattern (regex)
category: builtin
tags: [search, content]
---

# grep

Search file contents for a pattern using regex.

## Arguments

- `pattern` (required): Regular expression pattern to search for
- `path` (optional): Directory or file to search in (default: current directory)
- `glob` (optional): File pattern filter (default: `**/*`)
- `limit` (optional): Maximum number of matches (default: 50)
- `ignore_case` (optional): Case-insensitive search (default: false)

## Examples

Find function definitions:
```
##tool##
name: grep
args:
  pattern: "def \\w+\\("
  glob: "**/*.py"
##tool##
```

Case-insensitive search:
```
##tool##
name: grep
args:
  pattern: "todo|fixme"
  ignore_case: true
##tool##
```

## Output Format

Returns matches as `file:line: content`:
```
src/main.py:10: def main():
src/utils.py:25: def helper(x):
```
