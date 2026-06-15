#!/usr/bin/env python3
"""
UserPromptSubmit hook: injeta aviso de mensagens coord não lidas.
Fail-safe e barato: só age se ESTA sessão tem identidade coord (./.coordme ou
$COORD_ME) E existem não lidas. Qualquer erro -> no-op silencioso (exit 0).
"""
import os, sys, json, subprocess

def main():
    try:
        sys.stdin.read()  # consome o evento (ignora conteúdo)
    except Exception:
        pass
    try:
        # short-circuit rápido: sem identidade E sala vinculada, não faz nada (evita spawn)
        cwd = os.getcwd()
        has_id = os.environ.get("COORD_ME") or os.path.isfile(os.path.join(cwd, ".coordme"))
        has_room = os.environ.get("COORD_ROOM") or os.environ.get("COORD_DIR") \
            or os.path.isfile(os.path.join(cwd, ".coordroom"))
        root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if not has_id or not has_room or not root:
            return
        engine = os.path.join(root, "scripts", "coord.py")
        if not os.path.isfile(engine):
            return
        # encoding=utf-8: o engine emite UTF-8; sem isso o decode do pai (cp1252 no
        # Windows) vira mojibake no aviso injetado.
        out = subprocess.run([sys.executable or "python", engine, "inbox"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=8)
        text = (out.stdout or "").strip()
        if text.startswith("inbox ("):  # "inbox (N não lidas) ..." -> há não lidas
            msg = ("📨 coord: há mensagens não lidas de outro(s) Claude(s):\n"
                   + text + "\nUse o skill `coord` (ENGINE read) para ler.")
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": msg}}))
    except Exception:
        pass

main()
