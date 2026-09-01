import ast
import glob
import os
import re
import importlib.util

BACKEND_DIR = os.path.abspath("backend")
APP_DIR = os.path.join(BACKEND_DIR, "app")
ALEMBIC_DIR = os.path.join(BACKEND_DIR, "alembic")

def audit_all():
    print("=" * 70)
    print("COMPREHENSIVE BACKEND FORENSIC AUDIT SUITE")
    print("=" * 70)

    # 1. Collect all production files
    prod_files = []
    for root, dirs, files in os.walk(APP_DIR):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for f in files:
            if f.endswith(".py"):
                prod_files.append(os.path.join(root, f))
    
    for root, dirs, files in os.walk(ALEMBIC_DIR):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for f in files:
            if f.endswith(".py"):
                prod_files.append(os.path.join(root, f))

    print(f"Total production & migration files: {len(prod_files)}\n")

    # -------------------------------------------------------------
    # CHECK 1: Anti-Cheat / Facades / Dummy Methods / Canned Returns
    # -------------------------------------------------------------
    print(">>> CHECK 1: ANTI-CHEAT & FACADE DETECTION <<<")
    empty_or_trivial = []
    canned_patterns = []
    
    for fpath in prod_files:
        rel = os.path.relpath(fpath, BACKEND_DIR)
        with open(fpath, "r", encoding="utf-8") as fh:
            code = fh.read()
        
        try:
            tree = ast.parse(code, filename=fpath)
        except Exception as e:
            print(f"AST Error in {rel}: {e}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check for empty body (pass or docstring only or single return constant)
                body = node.body
                # filter out docstrings
                real_stmts = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
                if not real_stmts:
                    empty_or_trivial.append((rel, node.name, node.lineno, "Empty function / docstring only"))
                elif len(real_stmts) == 1:
                    stmt = real_stmts[0]
                    if isinstance(stmt, ast.Pass):
                        empty_or_trivial.append((rel, node.name, node.lineno, "Only 'pass'"))
                    elif isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
                        # ignore property getters or simple helpers if legitimate
                        empty_or_trivial.append((rel, node.name, node.lineno, f"Returns constant: {stmt.value.value}"))

    print(f"Found {len(empty_or_trivial)} trivial/single-statement functions to verify:")
    for rel, fn, lno, reason in empty_or_trivial:
        print(f"  - {rel}:{lno} in {fn}() -> {reason}")

    # -------------------------------------------------------------
    # CHECK 2: Multi-Tenancy Invariants
    # -------------------------------------------------------------
    print("\n>>> CHECK 2: MULTI-TENANCY INVARIANTS <<<")
    # Check all endpoints in app/api/*.py
    api_dir = os.path.join(APP_DIR, "api")
    for api_file in sorted(os.listdir(api_dir)):
        if not api_file.endswith(".py") or api_file == "__init__.py":
            continue
        api_path = os.path.join(api_dir, api_file)
        with open(api_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        
        print(f"Analyzing API router: app/api/{api_file}")
        # Find all route handlers (@router.get, post, delete, put, patch)
        tree = ast.parse(content, filename=api_path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # check decorators
                is_route = any(
                    isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "put", "delete", "patch")
                    for d in node.decorator_list
                )
                if is_route:
                    # check if current_user dependency is present
                    has_auth = "current_user" in [arg.arg for arg in node.args.args]
                    # check if public endpoint (e.g. login/register/health)
                    is_public = api_file in ("auth.py", "health.py")
                    print(f"  Endpoint {node.name}() -> Auth / current_user: {'YES' if has_auth else ('PUBLIC' if is_public else 'NO')}")

    # -------------------------------------------------------------
    # CHECK 3: Privacy Pipeline Invariants
    # -------------------------------------------------------------
    print("\n>>> CHECK 3: PRIVACY PIPELINE INVARIANTS <<<")
    privacy_dir = os.path.join(APP_DIR, "services", "privacy")
    for pfile in sorted(os.listdir(privacy_dir)):
        if pfile.endswith(".py"):
            ppath = os.path.join(privacy_dir, pfile)
            with open(ppath, "r", encoding="utf-8") as fh:
                pcontent = fh.read()
            print(f"Analyzing Privacy Module: app/services/privacy/{pfile}")
            if "entity_registry.py" in pfile:
                # verify registry storage
                if "self._registry" in pcontent or "self._entities" in pcontent or "self._mapping" in pcontent:
                    print("  [PASS] EntityRegistry uses in-memory dict storage.")
                if "db.add" in pcontent or "open(" in pcontent or "write(" in pcontent:
                    print("  [FAIL] EntityRegistry has file/db write operations!")
                else:
                    print("  [PASS] EntityRegistry does not persist to disk/db.")
            if "ner_masker.py" in pfile or "masking_pipeline.py" in pfile or "bank_matcher.py" in pfile:
                # check bracket notation
                bracket_matches = re.findall(r"\[[A-Z_]+_\d+\]|\[[A-Z_]+\]", pcontent)
                print(f"  Bracket notation samples found: {set(bracket_matches)}")
                # check financial number preservation
                if "comma" in pcontent.lower() or "number" in pcontent.lower() or "currency" in pcontent.lower():
                    print("  [PASS] Contains financial / numeric preservation handling.")

    # -------------------------------------------------------------
    # CHECK 4: Tech Stack, Requirements & Dockerfile Compliance
    # -------------------------------------------------------------
    print("\n>>> CHECK 4: TECH STACK & CONFIGURATION COMPLIANCE <<<")
    req_path = os.path.join(BACKEND_DIR, "requirements.txt")
    if os.path.exists(req_path):
        with open(req_path, "r", encoding="utf-8") as fh:
            reqs = fh.read()
        print("Auditing backend/requirements.txt:")
        forbidden_pkgs = ["passlib", "python-jose", "jose"]
        for pkg in forbidden_pkgs:
            if pkg in reqs:
                print(f"  [FAIL] Forbidden legacy package found in requirements.txt: {pkg}")
            else:
                print(f"  [PASS] No {pkg} found in requirements.txt.")
        
        required_pkgs = ["pyjwt", "bcrypt", "fastapi", "sqlalchemy", "pydantic", "nemoguardrails", "pinecone"]
        for pkg in required_pkgs:
            if pkg.lower() in reqs.lower():
                print(f"  [PASS] Required dependency present: {pkg}")
            else:
                print(f"  [WARN] Expected dependency missing from requirements.txt: {pkg}")

    docker_path = os.path.join(BACKEND_DIR, "Dockerfile")
    if os.path.exists(docker_path):
        with open(docker_path, "r", encoding="utf-8") as fh:
            docker_content = fh.read()
        print("\nAuditing backend/Dockerfile:")
        print(f"  Base image lines: {[l for l in docker_content.splitlines() if l.startswith('FROM')]}")
        print(f"  CMD lines: {[l for l in docker_content.splitlines() if l.startswith('CMD') or l.startswith('ENTRYPOINT')]}")

if __name__ == "__main__":
    audit_all()
