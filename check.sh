#!/usr/bin/env bash
# Every check this repo has, in one run. GitHub runs the same script on each
# pull request. Needs only Python 3: no token, no network. Run: ./check.sh
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

echo "== Every Python file compiles"
"$PY" - <<'EOF'
import pathlib, sys
bad = []
for p in sorted(pathlib.Path(".").rglob("*.py")):
    if "__pycache__" in p.parts:
        continue
    try:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
    except SyntaxError as e:
        bad.append(f"{p}:{e.lineno}: {e.msg}")
print("\n".join(bad) or "ok")
sys.exit(1 if bad else 0)
EOF

echo "== Telegram bot logic"
(cd clients/telegram && "$PY" test_logic.py)

echo "== Claude app skill calendar file"
(cd desktop && "$PY" test_make_ics.py)

echo "== The skill zip people download matches desktop/save-your-food/"
"$PY" - <<'EOF'
import pathlib, sys, zipfile
src = pathlib.Path("desktop/save-your-food")
want = {
    p.relative_to(src.parent).as_posix(): p.read_bytes()
    for p in src.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store"
}
with zipfile.ZipFile("desktop/save-your-food.zip") as z:
    have = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
problems = [f"missing from zip: {n}" for n in sorted(want.keys() - have.keys())]
problems += [f"in zip but not the folder: {n}" for n in sorted(have.keys() - want.keys())]
problems += [f"differs: {n}" for n in sorted(want.keys() & have.keys()) if want[n] != have[n]]
if problems:
    print("\n".join(problems))
    print("Rebuild it: see desktop/README.md, 'After changing the skill'.")
    sys.exit(1)
print("ok")
EOF

echo "== All checks passed"
