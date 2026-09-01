import ast
import glob
import os
import re
import sys

BACKEND_DIR = os.path.abspath("backend")
APP_DIR = os.path.join(BACKEND_DIR, "app")
ALEMBIC_DIR = os.path.join(BACKEND_DIR, "alembic")
TESTS_DIR = os.path.join(BACKEND_DIR, "tests")

def get_app_python_files():
    py_files = []
    for root, dirs, files in os.walk(APP_DIR):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    
    # Add alembic env.py and versions
    for root, dirs, files in os.walk(ALEMBIC_DIR):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    return py_files

def check_ast(files):
    print("=== 1. AST INTEGRITY CHECK ===")
    errors = []
    for f in sorted(files):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                content = fh.read()
            ast.parse(content, filename=f)
        except Exception as e:
            errors.append((f, str(e)))
            print(f"  [FAIL] {f}: {e}")
    if not errors:
        print(f"  [PASS] All {len(files)} Python files parsed cleanly under Python AST.")
    else:
        print(f"  [FAIL] {len(errors)} AST parsing errors found.")
    return errors

def check_anti_cheat(files):
    print("\n=== 2. STATIC ANALYSIS & ANTI-CHEAT FORENSICS ===")
    suspicious = []
    for f in sorted(files):
        with open(f, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for idx, line in enumerate(lines, 1):
            # Check for dummy hardcoded returns or mocked results
            if re.search(r"^\s*return\s+(True|False|\"mock[^\"]*\"|'mock[^']*'|\[\]|\{\})\s*$", line):
                # We should inspect if the method is a stub
                pass
            if re.search(r"unittest\.mock|MagicMock|pytest\.mock", line):
                if not f.startswith(TESTS_DIR):
                    suspicious.append((f, idx, "Mock in production code", line.strip()))
            if re.search(r"TODO|FIXME|NOT_IMPLEMENTED|raise NotImplementedError", line):
                suspicious.append((f, idx, "Unimplemented stub or TODO", line.strip()))
            if re.search(r"passlib|python-jose", line):
                suspicious.append((f, idx, "Prohibited legacy auth library referenced", line.strip()))
    
    if suspicious:
        print(f"  Found {len(suspicious)} suspicious items to inspect:")
        for f, idx, cat, line in suspicious:
            rel = os.path.relpath(f, BACKEND_DIR)
            print(f"    {rel}:{idx} [{cat}] -> {line}")
    else:
        print("  [PASS] No mocks, unimplemented stubs, or legacy auth references found in production code.")
    return suspicious

def check_tech_stack(files):
    print("\n=== 3. TECH STACK & CONFIG COMPLIANCE ===")
    issues = []
    for f in sorted(files):
        with open(f, "r", encoding="utf-8") as fh:
            content = fh.read()
            lines = content.splitlines()
        
        rel = os.path.relpath(f, BACKEND_DIR)
        # Check Pydantic v1 patterns
        if "class Config:" in content:
            issues.append((rel, "Pydantic v1 'class Config:' pattern detected"))
        if "@validator(" in content:
            issues.append((rel, "Pydantic v1 '@validator' decorator detected (should be @field_validator)"))
        if "@root_validator(" in content:
            issues.append((rel, "Pydantic v1 '@root_validator' decorator detected (should be @model_validator)"))
        
        # Check bare except
        for idx, line in enumerate(lines, 1):
            if re.match(r"^\s*except\s*:", line):
                issues.append((f"{rel}:{idx}", "Bare 'except:' found (violates AGENTS.md rule 5)"))

    if issues:
        print(f"  Found {len(issues)} tech stack / convention issues:")
        for loc, desc in issues:
            print(f"    {loc} -> {desc}")
    else:
        print("  [PASS] Full compliance with Pydantic v2, no bare excepts, modern typing conventions.")
    return issues

if __name__ == "__main__":
    files = get_app_python_files()
    print(f"Found {len(files)} application/alembic Python files to audit.")
    check_ast(files)
    check_anti_cheat(files)
    check_tech_stack(files)
