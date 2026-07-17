import os
import re
from collections import Counter

# Look for repeated patterns
try_except_count = 0
connection_handling = 0
auth_checks = 0

for root, dirs, files in os.walk("routers"):
    dirs[:] = [d for d in dirs if d not in {"__pycache__"}]
    for file in files:
        if not file.endswith(".py"):
            continue
        path = os.path.join(root, file)
        with open(path) as f:
            content = f.read()
            try_except_count += len(re.findall(r"try:", content))
            connection_handling += len(re.findall(r"conn\.close\(\)", content))
            auth_checks += len(re.findall(r"Depends\(require_roles", content))

print(f"Try-except blocks in routers/: {try_except_count}")
print(f"conn.close() calls in routers/: {connection_handling}")
print(f"require_roles dependency checks: {auth_checks}")
print()

# Look for type hints
typed_files = 0
untyped_functions = 0
for root, dirs, files in os.walk("routers"):
    dirs[:] = [d for d in dirs if d not in {"__pycache__"}]
    for file in files:
        if not file.endswith(".py"):
            continue
        path = os.path.join(root, file)
        with open(path) as f:
            content = f.read()
            # Count functions with incomplete type hints
            functions = re.findall(r"def (\w+)\((.*?)\):", content)
            for func_name, params in functions:
                if "->" not in params and "->" not in content.split(f"def {func_name}")[1].split("\n")[0]:
                    untyped_functions += 1

print(f"Functions with incomplete type hints: {untyped_functions}")
