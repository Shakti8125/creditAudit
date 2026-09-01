import ast
import glob
import os
import re

BACKEND_DIR = os.path.abspath("backend")
APP_DIR = os.path.join(BACKEND_DIR, "app")

def analyze_database_queries():
    print("==================================================")
    print("=== MULTI-TENANCY DATABASE QUERY AUDIT ===")
    print("==================================================")
    
    query_files = []
    for root, _, files in os.walk(APP_DIR):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                if "select(" in content or "delete(" in content or "update(" in content or "execute(" in content:
                    query_files.append((path, content))
    
    print(f"Found {len(query_files)} files containing SQLAlchemy database queries.\n")
    
    for path, content in query_files:
        rel = os.path.relpath(path, BACKEND_DIR)
        print(f"--- File: {rel} ---")
        lines = content.splitlines()
        tree = ast.parse(content, filename=path)
        
        # Look for functions containing queries
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_source = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                if any(k in func_source for k in ["select(", "delete(", "update(", ".execute("]):
                    # Check if tenant_id is in parameters or referenced in query
                    has_tenant_filter = "tenant_id" in func_source
                    print(f"  Line {node.lineno}: {node.name}()")
                    print(f"    tenant_id referenced: {'YES' if has_tenant_filter else 'NO'}")
                    # Print relevant select lines
                    for lno in range(node.lineno, node.end_lineno + 1):
                        line_str = lines[lno - 1]
                        if any(k in line_str for k in ["select(", "where(", "filter(", "tenant_id"]):
                            print(f"      [{lno}] {line_str.strip()}")
        print()

if __name__ == "__main__":
    analyze_database_queries()
