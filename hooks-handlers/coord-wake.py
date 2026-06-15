#!/usr/bin/env python3
"""
Stop hook: AUTO-WAKE. Quando o Claude vai encerrar o turno, puxa mensagens coord
novas dirigidas a ESTA identidade e, se houver, bloqueia o stop devolvendo-as ao
modelo (`{"decision":"block","reason":...}`) — o Claude "acorda" e trata sem
precisar de um Monitor vivo. Substitui o babysitting do watcher no caminho comum.

Fail-safe: sem identidade / sem novas / qualquer erro -> deixa parar (exit 0).
Loop-safe: `coord wake` tem cursor próprio -> cada msg acorda no máximo 1x.
"""
import os, sys, json, subprocess

def main():
    try:
        sys.stdin.read()  # consome o evento (ignora conteúdo)
    except Exception:
        pass
    try:
        # short-circuit: sem identidade E sala vinculada aqui, não faz nada (evita spawn).
        # Sem sala -> não participa de coord neste projeto -> nunca acorda.
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
        # encoding=utf-8: o engine emite UTF-8; sem isso o decode do pai quebraria
        # em assuntos com acento/emoji no Windows (cp1252).
        out = subprocess.run([sys.executable or "python", engine, "wake"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=8)
        text = (out.stdout or "").strip()
        if not text:
            return  # nada novo -> deixa o turno encerrar
        reason = (text + "\n\nAcima: mensagens coord novas dirigidas a você (auto-wake). "
                  "Leia com `coord read` e, se for pergunta, responda com `coord answer`. "
                  "Se já tratou tudo, é só encerrar — não vão te acordar de novo pelas mesmas.")
        print(json.dumps({"decision": "block", "reason": reason}))
    except Exception:
        pass

main()
