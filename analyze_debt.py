import os
import re
from pathlib import Path
from collections import defaultdict

# Count functions per file
files_by_size = defaultdict(lambda: {"lines": 0, "functions": 0, "classes": 0})

for root, dirs, files in os.walk("."):
    # Skip non-source
    dirs[:] = [d for d in dirs if d not in {".git", ".pytest_cache", "node_modules", ".venv", "__pycache__"}]
    
    for file in files:
        if not file.endswith(".py"):
            continue
        path = os.path.join(root, file)
        try:
            with open(path) as f:
                content = f.read()
                lines = len(content.splitlines())
                functions = len(re.findall(r"^def ", content, re.MULTILINE))
                classes = len(re.findall(r"^class ", content, re.MULTILINE))
                
                files_by_size[path] = {
                    "lines": lines,
                    "functions": functions,
                    "classes": classes,
                }
        except:
            pass

# Find large files (potential complexity)
large_files = sorted(files_by_size.items(), key=lambda x: x[1]["lines"], reverse=True)[:10]
print("=" * 60)
print("LARGE FILES (Potential Code Complexity)")
print("=" * 60)
for path, stats in large_files:
    if stats["lines"] > 100:
        print(f"{path}: {stats['lines']} lines, {stats['functions']} functions")

# Count functions per file (find dense files)
print("\n" + "=" * 60)
print("HIGH-FUNCTION FILES (Many responsibilities?)")
print("=" * 60)
dense = [(p, s) for p, s in files_by_size.items() if s["functions"] > 10]
dense.sort(key=lambda x: x[1]["functions"], reverse=True)
for path, stats in dense[:10]:
    avg_lines = stats["lines"] // max(stats["functions"], 1)
    print(f"{path}: {stats['functions']} functions, avg {avg_lines} lines each")
