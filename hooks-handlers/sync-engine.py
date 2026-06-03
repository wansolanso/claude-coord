#!/usr/bin/env python3
"""
SessionStart hook: sincroniza o engine para um caminho FIXO e portável
(~/.claude/coord-bin/coord.py), independente de onde o plugin foi instalado.
Assim o SKILL.md pode referenciar um único caminho que funciona em qualquer máquina.
Roda em hooks, onde $CLAUDE_PLUGIN_ROOT está disponível. Fail-safe (exit 0).
"""
import os, sys, shutil

def main():
    try:
        sys.stdin.read()
    except Exception:
        pass
    try:
        root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if root:
            src = os.path.join(root, "scripts", "coord.py")
            dst_dir = os.path.join(os.path.expanduser("~"), ".claude", "coord-bin")
            os.makedirs(dst_dir, exist_ok=True)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(dst_dir, "coord.py"))
    except Exception:
        pass
    sys.stdout.write("{}")

main()
