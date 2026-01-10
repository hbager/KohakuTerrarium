---
name: python
description: Execute Python code in a subprocess
category: builtin
tags: [code, execution, interpreter]
---

# python

Execute Python code in a subprocess and return output.

## WHEN TO USE

- Quick computations or data transformations
- Testing code snippets
- Checking Python environment/packages
- Complex string/data processing

## HOW TO USE

```xml
<python>code here</python>
```

## Arguments

| Arg | Type | Description |
|-----|------|-------------|
| code | body | Python code to execute (required) |

## Examples

```xml
<!-- Simple computation -->
<python>
result = sum(range(100))
print(f"Sum: {result}")
</python>

<!-- Check packages -->
<python>
import sys
print(f"Python {sys.version}")
</python>

<!-- Data processing -->
<python>
import json
data = {"name": "test", "values": [1, 2, 3]}
print(json.dumps(data, indent=2))
</python>
```

## Output Format

Returns stdout output from the Python process.

## LIMITATIONS

- Runs in isolated subprocess (no state persistence)
- Timeout applies (default: 30 seconds)
- Only packages installed in environment are available

## TIPS

- Use `print()` to output results
- For file operations, prefer `read`/`write` tools
- Check package availability before using
