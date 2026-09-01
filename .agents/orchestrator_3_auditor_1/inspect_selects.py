import os
import ast

backend_root = r"c:\Users\Shakti\Documents\CreditAudit- AI\backend\app"
api_dir = os.path.join(backend_root, "api")

for fn in sorted(os.listdir(api_dir)):
    if fn.endswith(".py") and fn not in ["__init__.py", "health.py", "deps.py"]:
        p = os.path.join(api_dir, fn)
        with open(p, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        print(f"\n--- Checking {fn} ---")
        for i, line in enumerate(lines, 1):
            if "select(" in line:
                # print the next 8 lines
                snippet = "".join(lines[i-1:min(i+7, len(lines))]).strip()
                print(f"Line {i}:\n{snippet}\n")
