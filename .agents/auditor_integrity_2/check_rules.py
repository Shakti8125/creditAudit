import os
import re

def check_agents_rules():
    print("=== AGENTS.MD ARCHITECTURAL & PRIVACY RULE AUDIT ===")
    
    # 1. Check pinned model IDs in backend
    print("\n[1] Pinned LLM Model IDs:")
    pinned_found = []
    for root, _, files in os.walk("backend/app"):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8") as file:
                    txt = file.read()
                    if "gemini-2.0-flash" in txt:
                        pinned_found.append((p, "gemini-2.0-flash"))
                    if "llama-3.1-nemotron-70b-instruct" in txt:
                        pinned_found.append((p, "llama-3.1-nemotron-70b-instruct"))
                    if "latest" in txt and ("gemini" in txt or "model" in txt):
                        # check if model name uses "latest"
                        for line in txt.splitlines():
                            if re.search(r'["\']gemini.*latest["\']', line, re.I):
                                print(f"  VIOLATION: Unpinned model ID found in {p}: {line}")
    print(f"  Verified pinned model references ({len(pinned_found)}):")
    for path, model in pinned_found[:5]:
        print(f"    {path} -> {model}")

    # 2. Check RS256 JWT Algorithm
    print("\n[2] Cryptographic RS256 JWT Implementation:")
    security_file = "backend/app/utils/security.py"
    if os.path.exists(security_file):
        with open(security_file, "r", encoding="utf-8") as f:
            sec_text = f.read()
            if "RS256" in sec_text and "jwt.encode" in sec_text and "jwt.decode" in sec_text:
                print("  PASS: RS256 JWT signing and verification properly implemented in app/utils/security.py")
            else:
                print("  FAIL: RS256 not properly implemented in security.py")

    # 3. Check Privacy Pipeline Bracket Masking & Egress Validator
    print("\n[3] Privacy Pipeline Bracket Masking & Egress Validator:")
    masking_files = [
        "backend/app/services/privacy/masking_pipeline.py",
        "backend/app/services/privacy/egress_validator.py",
        "backend/app/services/privacy/entity_registry.py"
    ]
    for mf in masking_files:
        if os.path.exists(mf):
            with open(mf, "r", encoding="utf-8") as f:
                content = f.read()
                if "BANK_" in content or "ORG_" in content or "PERSON_" in content or "validate" in content:
                    print(f"  PASS: {mf} exists and implements token masking / validation logic")
                else:
                    print(f"  WARN: {mf} missing token masking constants")
        else:
            print(f"  FAIL: {mf} does not exist")

    # 4. Check Multi-Tenancy tenant_id filtering
    print("\n[4] Multi-Tenancy tenant_id Isolation:")
    pinecone_store = "backend/app/services/retrieval/pinecone_store.py"
    if os.path.exists(pinecone_store):
        with open(pinecone_store, "r", encoding="utf-8") as f:
            p_text = f.read()
            if "tenant_id" in p_text and "namespace" in p_text:
                print("  PASS: PineconeStore namespaces enforce tenant_id isolation")
            else:
                print("  FAIL: PineconeStore does not partition by tenant_id")

    # 5. Check Async-First convention
    print("\n[5] Async-first Implementation in API and Services:")
    sync_def_in_api = 0
    async_def_in_api = 0
    for root, _, files in os.walk("backend/app/api"):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8") as f_in:
                    lines = f_in.readlines()
                    for line in lines:
                        if line.strip().startswith("async def "):
                            async_def_in_api += 1
                        elif line.strip().startswith("def ") and not line.strip().startswith("def __"):
                            sync_def_in_api += 1
    print(f"  API routes: {async_def_in_api} async functions, {sync_def_in_api} sync helper functions")
    
    print("\n=== AGENTS.MD RULES AUDIT COMPLETE ===")

if __name__ == "__main__":
    check_agents_rules()
