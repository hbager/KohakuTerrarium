---
name: write
description: Write content to a file (creates or overwrites)
category: builtin
tags: [file, io]
---

# write

Write content to a file. Creates the file if it doesn't exist, overwrites if it does.

## Arguments

- `path` (required): Path to the file to write
- `content` (required): Content to write to the file

## Examples

Create a new Python file:
```
##tool##
name: write
args:
  path: src/hello.py
  content: |
    def hello():
        print("Hello, World!")

    if __name__ == "__main__":
        hello()
##tool##
```

## Output Format

Returns confirmation with file info:
```
Created /path/to/file.py (15 lines, 342 bytes)
```

## Notes

- Creates parent directories automatically if they don't exist
- Overwrites existing files completely (no merge/append)
- Content uses YAML multiline syntax (`|`) for proper formatting
