#!/usr/bin/env python3
"""
SessionStart hook: sincroniza o engine + launcher para um caminho FIXO e portável
(~/.claude/coord-bin/), independente de onde o plugin foi instalado. Assim o SKILL.md
referencia um único caminho que funciona em qualquer máquina/OS.
Roda em hooks, onde $CLAUDE_PLUGIN_ROOT está disponível. Fail-safe (exit 0).
"""
import os, sys, shutil, stat

def main():
    try:
        sys.stdin.read()
    except Exception:
        pass
    try:
        root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if root:
            scripts = os.path.join(root, "scripts")
            dst_dir = os.path.join(os.path.expanduser("~"), ".claude", "coord-bin")
            os.makedirs(dst_dir, exist_ok=True)
            for name in ("coord.py", "coord"):
                src = os.path.join(scripts, name)
                if os.path.isfile(src):
                    dst = os.path.join(dst_dir, name)
                    shutil.copy2(src, dst)
                    if name == "coord":  # garante bit de execução no launcher
                        st = os.stat(dst)
                        os.chmod(dst, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass
    sys.stdout.write("{}")

main()
