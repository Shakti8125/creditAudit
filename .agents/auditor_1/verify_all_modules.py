import ast
import glob
import os
import re

BACKEND_DIR = os.path.abspath("backend")

def inspect_models():
    print("=== INSPECTING MODELS ===")
    models_dir = os.path.join(BACKEND_DIR, "app", "models")
    for f in sorted(os.listdir(models_dir)):
        if f.endswith(".py") and f != "__init__.py":
            path = os.path.join(models_dir, f)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            # check DeclarativeBase / Mapped / mapped_column
            has_mapped = "Mapped[" in content
            has_mapped_col = "mapped_column" in content
            print(f"Model file: app/models/{f}")
            print(f"  Uses Mapped[]: {has_mapped}, Uses mapped_column: {has_mapped_col}")
            # check tenant_id presence if multi-tenant
            if "tenant_id" in content:
                print(f"  Contains tenant_id column: YES")

def inspect_schemas():
    print("\n=== INSPECTING SCHEMAS ===")
    schemas_dir = os.path.join(BACKEND_DIR, "app", "schemas")
    for f in sorted(os.listdir(schemas_dir)):
        if f.endswith(".py") and f != "__init__.py":
            path = os.path.join(schemas_dir, f)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            has_v1_config = "class Config:" in content
            has_v2_config = "model_config = ConfigDict(" in content
            has_pydantic_import = "pydantic" in content
            print(f"Schema file: app/schemas/{f}")
            print(f"  V1 Config: {has_v1_config}, V2 ConfigDict: {has_v2_config}, Imports Pydantic: {has_pydantic_import}")

def inspect_services():
    print("\n=== INSPECTING SERVICES ===")
    services_dir = os.path.join(BACKEND_DIR, "app", "services")
    for root, _, files in os.walk(services_dir):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                path = os.path.join(root, f)
                rel = os.path.relpath(path, BACKEND_DIR)
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                # Check for async functions
                tree = ast.parse(content, filename=path)
                async_fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
                sync_fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
                print(f"{rel}: {len(async_fns)} async funcs, {len(sync_fns)} sync funcs")

def inspect_alembic():
    print("\n=== INSPECTING ALEMBIC ===")
    env_path = os.path.join(BACKEND_DIR, "alembic", "env.py")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        has_async = "async" in content or "run_async" in content or "connectable.connect()" in content
        print(f"alembic/env.py: async support = {has_async}")

if __name__ == "__main__":
    inspect_models()
    inspect_schemas()
    inspect_services()
    inspect_alembic()
