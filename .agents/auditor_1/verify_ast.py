import ast
import glob
import os
import sys

def main():
    root = os.path.abspath("backend")
    files = glob.glob(os.path.join(root, "**", "*.py"), recursive=True)
    print(f"Total Python files found: {len(files)}")
    errors = []
    for f in sorted(files):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                code = fh.read()
            ast.parse(code, filename=f)
        except Exception as e:
            errors.append((f, str(e)))
            print(f"FAIL: {f} -> {e}")
    if not errors:
        print("PASS: All Python files parsed successfully via AST!")
    else:
        print(f"FAILED: {len(errors)} files failed AST parsing.")
        sys.exit(1)

if __name__ == "__main__":
    main()
