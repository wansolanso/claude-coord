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
        # short-circuit rápido: sem identidade aqui, não faz nada (evita spawn)
        has_id = os.environ.get("COORD_ME") or os.path.isfile(
            os.path.join(os.getcwd(), ".coordme"))
        root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if not has_id or not root:
            return
        engine = os.path.join(root, "scripts", "coord.py")
        if not os.path.isfile(engine):
            return
        out = subprocess.run([sys.executable or "python", engine, "inbox"],
                             capture_output=True, text=True, timeout=8)
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
