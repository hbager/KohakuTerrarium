---
name: read
description: Read file contents with optional line range
category: builtin
tags: [file, io]
---

# read

Read file contents with optional line range.

## Arguments

- `path` (required): Path to the file to read
- `offset` (optional): Starting line number (0-based, default: 0)
- `limit` (optional): Maximum number of lines to read (default: all)

## Examples

Read entire file:
```
##tool##
name: read
args:
  path: src/main.py
##tool##
```

Read lines 10-30:
```
##tool##
name: read
args:
  path: src/main.py
  offset: 10
  limit: 20
##tool##
```

## Output Format

Returns file contents with line numbers:
```
     1→first line content
     2→second line content
     3→...
```

If limit is applied, shows truncation notice:
```
... (showing lines 11-30 of 500)
```

## Notes

- Uses UTF-8 encoding with error replacement for binary data
- Long lines are preserved (no truncation within lines)
- Use offset/limit for large files to avoid context overflow
