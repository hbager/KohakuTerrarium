---
name: bash
description: Execute shell commands and return output
category: builtin
tags: [shell, command, system]
---

# bash

Execute shell commands and return output.

## Arguments

- `command` (required): The command to execute

## Examples

List files:
```
##tool##
name: bash
args:
  command: ls -la
##tool##
```

Check git status:
```
##tool##
name: bash
args:
  command: git status
##tool##
```

Run tests:
```
##tool##
name: bash
args:
  command: pytest tests/ -v
##tool##
```

Install dependencies:
```
##tool##
name: bash
args:
  command: pip install -r requirements.txt
##tool##
```

## Output Format

Returns combined stdout and stderr:
```
total 24
drwxr-xr-x  5 user  staff   160 Jan 10 12:00 .
drwxr-xr-x  3 user  staff    96 Jan 10 11:00 ..
-rw-r--r--  1 user  staff  1234 Jan 10 12:00 main.py
```

Exit code is included in result metadata.

## Platform Notes

- **Windows**: Commands run in PowerShell (pwsh if available, otherwise powershell)
- **Unix/Linux/Mac**: Commands run in bash (or sh if bash unavailable)

## Notes

- Commands have a configurable timeout (default: 30 seconds)
- Large outputs may be truncated
- Use for system commands, git, package managers, build tools
- For file operations, prefer `read`/`write`/`glob`/`grep` tools
