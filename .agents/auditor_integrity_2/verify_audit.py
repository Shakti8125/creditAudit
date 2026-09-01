import os
import sys
import time
import json
import re
import py_compile

def run_checks():
    print("=== FORENSIC INTEGRITY AUDIT SUITE ===")
    
    # 1. Check Source Immutability
    # The current task prompt was dispatched at 2026-08-31T17:28:09Z (roughly 22:58 local time)
    # Let's check any file modified in backend/, frontend/, deploy/ in the last 4 hours
    cutoff = time.time() - (4 * 3600)
    modified_app_files = []
    
    for folder in ['backend', 'frontend', 'deploy']:
        if os.path.exists(folder):
            for root, dirs, files in os.walk(folder):
                # skip ignored directories
                dirs[:] = [d for d in dirs if d not in ['node_modules', '.venv', 'dist', '.pytest_cache', '__pycache__']]
                for f in files:
                    full_path = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(full_path)
                        if mtime > cutoff:
                            modified_app_files.append((full_path, time.ctime(mtime)))
                    except Exception as e:
                        print(f"Error checking {full_path}: {e}")
                        
    print(f"\n[CHECK 1] Application Source Code Immutability:")
    print(f"  Target directories: backend/, frontend/, deploy/")
    print(f"  Modified file count in last 4 hours: {len(modified_app_files)}")
    for p, t in modified_app_files:
        print(f"    Modified: {p} (mtime: {t})")
        
    # 2. Check deployment_steps.md
    print(f"\n[CHECK 2] deployment_steps.md Authenticity & Completeness:")
    doc_path = "deployment_steps.md"
    if not os.path.exists(doc_path):
        print("  FAIL: deployment_steps.md does not exist!")
        return
        
    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    line_count = len(content.splitlines())
    byte_count = len(content.encode('utf-8'))
    print(f"  File size: {byte_count} bytes, {line_count} lines")
    
    # Search for forbidden placeholder / dummy tokens
    dummy_patterns = [r'\bTODO\b', r'\bFIXME\b', r'\bTBD\b', r'\blorem\b', r'\bdummy\b', r'\bnot implemented\b']
    dummy_matches = {}
    for pat in dummy_patterns:
        matches = re.findall(pat, content, re.IGNORECASE)
        if matches:
            dummy_matches[pat] = len(matches)
    print(f"  Dummy / placeholder matches: {dummy_matches}")
    
    # Parse all JSON code blocks
    json_blocks = re.findall(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    print(f"  Found {len(json_blocks)} JSON blocks in document:")
    all_json_valid = True
    for i, block in enumerate(json_blocks):
        try:
            parsed = json.loads(block)
            print(f"    JSON Block {i+1}: VALID ({type(parsed).__name__} with {len(parsed)} keys)")
        except Exception as e:
            print(f"    JSON Block {i+1}: INVALID - {e}")
            all_json_valid = False
            
    # Check bash commands in document
    bash_blocks = re.findall(r'```bash\s*(.*?)\s*```', content, re.DOTALL)
    print(f"  Found {len(bash_blocks)} Bash blocks containing deployment & validation commands.")
    
    # 3. Environment Variables Parity Verification
    print(f"\n[CHECK 3] Configuration & Environment Variables Verification:")
    # Extract config.py env vars
    config_path = "backend/app/config.py"
    config_vars = []
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            c_text = f.read()
            # find all fields in Settings or config classes
            for line in c_text.splitlines():
                m = re.match(r'^\s+([A-Z0-9_]+)\s*:\s*', line)
                if m:
                    config_vars.append(m.group(1))
    print(f"  Backend config variables detected ({len(config_vars)}): {config_vars}")
    missing_vars = [v for v in config_vars if v not in content]
    print(f"  Missing variables in deployment_steps.md: {missing_vars}")
    
    # 4. Backend Python Syntax Compilation
    print(f"\n[CHECK 4] Backend Bytecode Compilation Check:")
    py_errors = 0
    total_py = 0
    for root, dirs, files in os.walk("backend/app"):
        for f in files:
            if f.endswith(".py"):
                total_py += 1
                fp = os.path.join(root, f)
                try:
                    py_compile.compile(fp, doraise=True)
                except Exception as e:
                    print(f"  Compilation error in {fp}: {e}")
                    py_errors += 1
    print(f"  Compiled {total_py} python source files in backend/app/ with {py_errors} errors.")
    
    print("\n=== AUDIT SUITE FINISHED ===")

if __name__ == "__main__":
    run_checks()
