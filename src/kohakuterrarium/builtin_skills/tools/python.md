---
name: python
description: Execute Python code in a subprocess
category: builtin
tags: [code, execution, interpreter]
---

# python

Execute Python code in a subprocess and return output.

## Arguments

- `code` (required): Python code to execute

## Examples

Simple computation:
```
##tool##
name: python
args:
  code: |
    result = sum(range(100))
    print(f"Sum: {result}")
##tool##
```

Check Python version and packages:
```
##tool##
name: python
args:
  code: |
    import sys
    print(f"Python {sys.version}")

    import pkg_resources
    for pkg in ['numpy', 'pandas', 'requests']:
        try:
            version = pkg_resources.get_distribution(pkg).version
            print(f"{pkg}: {version}")
        except:
            print(f"{pkg}: not installed")
##tool##
```

Data processing:
```
##tool##
name: python
args:
  code: |
    import json

    data = {"name": "test", "values": [1, 2, 3]}
    print(json.dumps(data, indent=2))
##tool##
```

## Output Format

Returns stdout from the Python subprocess:
```
Python 3.11.0 (main, Oct 24 2022, 18:26:48)
numpy: 1.24.0
pandas: 2.0.0
requests: 2.28.0
```

Exit code is included in result metadata.

## Notes

- Runs in a separate subprocess (isolated from the agent)
- Has access to installed packages in the environment
- stdout and stderr are captured and combined
- Useful for quick computations, data transformations, testing snippets
- Has configurable timeout (default: 30 seconds)
- For persistent files, use the `write` tool instead
