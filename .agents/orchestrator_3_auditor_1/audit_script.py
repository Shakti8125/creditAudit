import os
import re
import ast

backend_root = r"c:\Users\Shakti\Documents\CreditAudit- AI\backend\app"

print("=" * 60)
print("1. CHECKING FOR ENTITY REGISTRY PERSISTENCE (DISK / DB)")
print("=" * 60)
# Verify EntityRegistry and RegistryStore
registry_store_path = os.path.join(backend_root, "services", "privacy", "registry_store.py")
with open(registry_store_path, "r", encoding="utf-8") as f:
    code = f.read()
    print("registry_store.py contents check:")
    if "self._store" in code and "dict" in code:
        print("  [OK] Uses in-memory dict (_store)")
    if "open(" in code or "sqlite" in code or "postgresql" in code or "execute(" in code:
        print("  [ALERT] Potential disk/DB in registry_store!")
    else:
        print("  [OK] No disk or DB access found in registry_store.py")

entity_reg_path = os.path.join(backend_root, "services", "privacy", "entity_registry.py")
with open(entity_reg_path, "r", encoding="utf-8") as f:
    code = f.read()
    if "open(" in code or "sqlite" in code or "save" in code.lower() and "def save" in code:
        print("  [ALERT] Potential disk persistence in entity_registry.py!")
    else:
        print("  [OK] No disk or DB access found in entity_registry.py")

print("\n" + "=" * 60)
print("2. CHECKING LLM CALL SITES & EGRESS VALIDATOR ENFORCEMENT")
print("=" * 60)
llm_call_files = []
for dp, _, fns in os.walk(backend_root):
    for fn in fns:
        if fn.endswith(".py"):
            p = os.path.join(dp, fn)
            with open(p, "r", encoding="utf-8") as fh:
                txt = fh.read()
                if "llm_router" in txt or "generate(" in txt or "generate_stream(" in txt:
                    if "def " in txt and ("api" in p or "services" in p):
                        if fn not in ["router.py", "base_provider.py", "nvidia_provider.py", "gemini_provider.py", "circuit_breaker.py"]:
                            llm_call_files.append((p, fn))

for path, fn in llm_call_files:
    with open(path, "r", encoding="utf-8") as fh:
        txt = fh.read()
        has_egress = "egress_validator" in txt or "EgressValidator" in txt
        print(f"File: {fn} -> EgressValidator present: {has_egress}")

print("\n" + "=" * 60)
print("3. CHECKING COMMA-PRESERVED FINANCIAL NUMBERS IN PRIVACY")
print("=" * 60)
ner_masker_path = os.path.join(backend_root, "services", "privacy", "ner_masker.py")
with open(ner_masker_path, "r", encoding="utf-8") as fh:
    code = fh.read()
    if "is_financial_number" in code or "FINANCIAL" in code or "PROTECTED" in code or r"\d{1,3}(?:,\d{3})+" in code:
        print("  [OK] Financial number pattern and protection found in ner_masker.py")
    else:
        print("  [ALERT] Financial number pattern missing in ner_masker.py")

print("\n" + "=" * 60)
print("4. CHECKING SQL QUERIES FOR TENANT_ID ISOLATION IN API")
print("=" * 60)
api_dir = os.path.join(backend_root, "api")
for fn in os.listdir(api_dir):
    if fn.endswith(".py") and fn not in ["__init__.py", "health.py", "deps.py"]:
        p = os.path.join(api_dir, fn)
        with open(p, "r", encoding="utf-8") as fh:
            txt = fh.read()
            tree = ast.parse(txt, filename=p)
            selects = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "select"]
            print(f"API {fn}: {len(selects)} select statements at lines {selects}")
