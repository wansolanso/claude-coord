#!/usr/bin/env python3
"""
coord - coordenação entre agentes Claude. Conflict-free, token-mínimo.

Modelo:
  - Cada mensagem = 1 arquivo em messages/  (nome único -> zero conflito de escrita)
  - feed.log = 1 linha por mensagem (append atômico) -> alimenta o watcher `tail -F`
  - state/  = cursores de leitura por-agente + overrides de status (open->answered)

Identidade: --me NAME  |  $COORD_ME  |  <cwd>/.coordme  (escrito por `init`)
Sala (base): $COORD_DIR  |  default ~/.claude/coord-room  (estável, cross-project)

Verbos: init send inbox read open answer watch whoami help
"""
import os, sys, time, glob, argparse, textwrap

BASE = os.environ.get("COORD_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "coord-room")
MSG  = os.path.join(BASE, "messages")
STA  = os.path.join(BASE, "state")
STT  = os.path.join(STA, "status")
FEED = os.path.join(BASE, "feed.log")

def _ensure():
    for d in (MSG, STA, STT):
        os.makedirs(d, exist_ok=True)

# ---------- identidade ----------
def me_from(args):
    if getattr(args, "me", None):
        return args.me
    if os.environ.get("COORD_ME"):
        return os.environ["COORD_ME"]
    p = os.path.join(os.getcwd(), ".coordme")
    if os.path.isfile(p):
        return open(p, encoding="utf-8").read().strip()
    sys.exit("erro: não sei quem você é. Rode `coord init <nome>` ou passe --me <nome>.")

# ---------- ids ----------
def next_seq(name):
    f = os.path.join(STA, f"seq-{name}")
    n = (int(open(f).read().strip()) if os.path.isfile(f) else 0) + 1
    open(f, "w").write(str(n))          # só o próprio agente escreve seu seq -> sem conflito
    return n

def human_id(name, n):
    return time.strftime("%Y-%m-%d-%H%M") + f"-{name}-{n}"

# ---------- status override ----------
def status_path(mid):  # filename-safe
    return os.path.join(STT, mid.replace(os.sep, "_"))

def eff_status(mid, declared):
    p = status_path(mid)
    return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else declared

# ---------- parsing de mensagem ----------
def parse(path):
    txt = open(path, encoding="utf-8").read()
    head, _, body = txt.partition("\n\n")
    m = {"_path": path, "_body": body.strip(), "_ms": int(os.path.basename(path).split("__", 1)[0])}
    for line in head.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            m[k.strip().upper()] = v.strip()
    return m

def all_msgs():
    return sorted(glob.glob(os.path.join(MSG, "*.md")),
                  key=lambda p: int(os.path.basename(p).split("__", 1)[0]))

def resolve(idsub, tipo=None):
    s = idsub.lower()
    hits = []
    for p in all_msgs():
        m = parse(p)
        if tipo and m.get("TIPO") != tipo: continue
        if s in m.get("ID", "").lower() or s in m.get("ASSUNTO", "").lower():
            hits.append(m)
    if not hits: sys.exit(f"erro: nenhuma msg casa '{idsub}'")
    if len(hits) > 1:
        ids = ", ".join(h["ID"] for h in hits)
        sys.exit(f"erro: '{idsub}' é ambíguo ({len(hits)}): {ids}")
    return hits[0]

# ---------- cursor ----------
def cursor(name):
    f = os.path.join(STA, f"cursor-{name}")
    return int(open(f).read().strip()) if os.path.isfile(f) else 0

def set_cursor(name, ms):
    open(os.path.join(STA, f"cursor-{name}"), "w").write(str(ms))

# ---------- escrita ----------
def write_msg(de, para, tipo, assunto, body, ref=None, status=None):
    _ensure()
    if status is None:
        status = "aberta" if tipo == "pergunta" else "informativa"
    n = next_seq(de)
    mid = human_id(de, n)
    ms = int(time.time() * 1000)
    head = [f"ID: {mid}", f"DE: {de}", f"PARA: {para}", f"TIPO: {tipo}"]
    if ref: head.append(f"REF: {ref}")
    head += [f"STATUS: {status}", f"ASSUNTO: {assunto}"]
    content = "\n".join(head) + "\n\n" + (body.strip() if body else "") + "\n"
    fname = f"{ms}__{mid}.md"
    final = os.path.join(MSG, fname)
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, final)              # rename atômico -> nunca half-write
    feed = f"FROM={de} TO={para} TYPE={tipo} STATUS={status} ID={mid} SUBJ={assunto}\n"
    with open(FEED, "a", encoding="utf-8") as fh:  # append pequeno = atômico
        fh.write(feed)
    return mid, ms

# ---------- comandos ----------
def c_init(a):
    name = a.name
    open(os.path.join(os.getcwd(), ".coordme"), "w", encoding="utf-8").write(name)
    body = a.body or ""
    extra = []
    if a.modifies:  extra.append(f"**Modifico:** {a.modifies}")
    if a.reserves:  extra.append(f"**Reservo p/ outros:** {a.reserves}")
    if extra: body = (body + "\n\n" + "\n".join(extra)).strip()
    if not body:
        body = f"Sou **{name}**. Entrando na sessão de coordenação."
    mid, _ = write_msg(name, "todos", "aviso", f"identidade: {name}", body, status="informativa")
    print(f"ok: identidade '{name}' salva em ./.coordme  |  intro postada {mid}")
    print(f"watcher: python \"{__file__}\" watch")

def c_send(a):
    de = me_from(a)
    body = a.body if a.body is not None else (sys.stdin.read() if not sys.stdin.isatty() else "")
    mid, _ = write_msg(de, a.to, a.type, a.subject, body, ref=a.ref, status=a.status)
    print(f"enviado {mid}  (DE {de} PARA {a.to} {a.type})")

def _fmt_line(m):
    st = eff_status(m["ID"], m.get("STATUS", ""))
    tag = f" [{st}]" if m.get("TIPO") == "pergunta" else ""
    return f'{m["ID"]}  {m.get("DE","?")}->{m.get("PARA","?")}  {m.get("TIPO",""):<9} "{m.get("ASSUNTO","")}"{tag}'

def _inbox_for(me):
    cur = cursor(me)
    out = []
    for p in all_msgs():
        m = parse(p)
        if m["_ms"] <= cur: continue
        if m.get("DE") == me: continue
        if m.get("PARA") not in (me, "todos"): continue
        out.append(m)
    return out

def c_inbox(a):
    me = me_from(a)
    msgs = _inbox_for(me)
    if not msgs:
        print("inbox: 0 não lidas"); return
    print(f"inbox ({len(msgs)} não lidas)  [`read` p/ abrir e marcar lido]")
    for m in msgs:
        print("  " + _fmt_line(m))

def c_read(a):
    me = me_from(a)
    if a.id:
        m = resolve(a.id)
        _print_full(m)
        set_cursor(me, max(cursor(me), m["_ms"]))
        return
    msgs = _inbox_for(me)
    if not msgs:
        print("nada novo."); return
    for m in msgs:
        _print_full(m); print()
    set_cursor(me, max(m["_ms"] for m in msgs))
    print(f"-- {len(msgs)} marcadas como lidas --")

def _print_full(m):
    st = eff_status(m["ID"], m.get("STATUS", ""))
    print(f'--- {m["ID"]}')
    print(f'DE {m.get("DE")} -> {m.get("PARA")} | {m.get("TIPO")} | STATUS {st}'
          + (f' | REF {m["REF"]}' if m.get("REF") else ""))
    print(f'ASSUNTO: {m.get("ASSUNTO","")}')
    if m["_body"]: print("\n" + m["_body"])

def c_open(a):
    me = me_from(a)
    found = False
    for p in all_msgs():
        m = parse(p)
        if m.get("TIPO") != "pergunta": continue
        if m.get("DE") == me: continue                       # nunca a sua própria pergunta
        if eff_status(m["ID"], m.get("STATUS", "")) != "aberta": continue
        if m.get("PARA") not in (me, "todos"): continue      # só dirigidas a você ou broadcast
        print("  " + _fmt_line(m)); found = True
    if not found: print("nenhuma pergunta aberta pra você.")

def c_answer(a):
    me = me_from(a)
    q = resolve(a.id, tipo="pergunta")
    if q.get("DE") == me:
        sys.exit(f"erro: '{q['ID']}' é sua própria pergunta — você não responde a si mesmo.")
    if q.get("TIPO") != "pergunta":
        sys.exit(f"erro: '{q['ID']}' não é uma pergunta (TIPO={q.get('TIPO')}).")
    if q.get("PARA") not in (me, "todos"):
        sys.exit(f"erro: '{q['ID']}' foi dirigida a {q.get('PARA')}, não a você. Não responda o que não é pra você.")
    body = a.body if a.body is not None else (sys.stdin.read() if not sys.stdin.isatty() else "")
    to = a.to or q.get("DE", "todos")
    mid, _ = write_msg(me, to, "resposta", f're: {q.get("ASSUNTO","")}', body, ref=q["ID"], status="informativa")
    open(status_path(q["ID"]), "w", encoding="utf-8").write("respondida")  # flip da origem (override, não edita o arquivo)
    print(f"respondido {mid}  | {q['ID']} -> respondida")

def c_watch(a):
    me = me_from(a)
    if not os.path.isfile(FEED):
        open(FEED, "a").close()
    import subprocess
    cmd = ["bash", "-c",
           f'tail -n 0 -F "{FEED}" 2>/dev/null | grep --line-buffered -Ev "^FROM={me} "']
    print(f"[watch] {me}: ouvindo feed, ignorando self. Ctrl-C p/ sair.", flush=True)
    os.execvp(cmd[0], cmd)

def c_whoami(a):
    print(me_from(a))

def c_help(a):
    print(textwrap.dedent("""\
    coord - coordenação entre agentes Claude (conflict-free, token-mínimo)

      init <nome> [--modifies "X,Y"] [--reserves "Z"] [--body "..."]
            registra identidade (grava ./.coordme) e posta a intro obrigatória.
      send --to <nome|todos> --type <aviso|pergunta|resposta|decisao|bloqueio>
           --subject "..." [--ref ID] [--status ...] [--body "..." | stdin]
      inbox            lista não lidas (não consome)
      read [ID]        abre msg(s); sem ID = todas não lidas + marca lido
      open             perguntas abertas dirigidas a você
      answer <ID> [--to X] [--body "..."|stdin]   responde E fecha a pergunta
      watch            sobe o watcher tail -F (rodar como background task)
      whoami / help

    Identidade: --me NAME | $COORD_ME | ./.coordme   |   Base: $COORD_DIR | dir do script
    """))

def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--me")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init"); s.add_argument("name")
    s.add_argument("--modifies"); s.add_argument("--reserves"); s.add_argument("--body")
    s.set_defaults(fn=c_init)

    s = sub.add_parser("send")
    s.add_argument("--to", required=True); s.add_argument("--type", required=True)
    s.add_argument("--subject", required=True); s.add_argument("--ref"); s.add_argument("--status")
    s.add_argument("--body"); s.set_defaults(fn=c_send)

    s = sub.add_parser("inbox"); s.set_defaults(fn=c_inbox)
    s = sub.add_parser("read"); s.add_argument("id", nargs="?"); s.set_defaults(fn=c_read)
    s = sub.add_parser("open"); s.set_defaults(fn=c_open)
    s = sub.add_parser("answer"); s.add_argument("id"); s.add_argument("--to"); s.add_argument("--body")
    s.set_defaults(fn=c_answer)
    s = sub.add_parser("watch"); s.set_defaults(fn=c_watch)
    s = sub.add_parser("whoami"); s.set_defaults(fn=c_whoami)
    s = sub.add_parser("help"); s.set_defaults(fn=c_help)

    a = p.parse_args()
    if not getattr(a, "cmd", None):
        c_help(a); return
    a.fn(a)

if __name__ == "__main__":
    main()
