#!/usr/bin/env python3
"""
coord - coordenação entre agentes Claude. Conflict-free, token-mínimo.

Modelo:
  - SALAS são entidades separadas: cada sala = 1 diretório próprio. Dois Claudes só se
    enxergam na MESMA sala. Você se vincula a uma sala por projeto com `join`.
  - Cada mensagem = 1 arquivo em <sala>/messages/  (nome único -> zero conflito de escrita)
  - feed.log = 1 linha por mensagem (append atômico) -> alimenta o watcher (tail nativo em Python)
  - state/  = cursores por-agente + overrides de status + registro de membros (pasta de cada)

Identidade: --me NAME  |  $COORD_ME  |  <cwd>/.coordme  (escrito por `join`/`init`)
Sala ativa: --room NAME | $COORD_ROOM | <cwd>/.coordroom (escrito por `join`)  |  $COORD_DIR (path direto)
            dirs sob $COORD_ROOMS_BASE (default ~/.claude/coord-rooms/<sala>)

Verbos: rooms join room state | link unlink move nest unnest (DAG) | init send inbox
        read open answer watch wake whoami help
"""
import os, sys, time, glob, argparse, textwrap, re

HOME = os.path.expanduser("~")
# Salas são entidades separadas, cada uma um diretório sob esta base.
ROOMS_BASE = os.environ.get("COORD_ROOMS_BASE") or os.path.join(HOME, ".claude", "coord-rooms")
ROOM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Caminhos da sala ATIVA — preenchidos por _set_room()/bind_room() a cada comando.
BASE = MSG = STA = STT = FEED = None

def _set_room(d):
    global BASE, MSG, STA, STT, FEED
    BASE = d
    MSG  = os.path.join(d, "messages")
    STA  = os.path.join(d, "state")
    STT  = os.path.join(STA, "status")
    FEED = os.path.join(d, "feed.log")

def _utf8_io():
    # stdin/stdout/stderr em UTF-8 — sem isso, no Windows (console default = cp1252):
    #  - out/err: `read`/`inbox`/`watch` quebram com UnicodeEncodeError;
    #  - in: corpo vindo por `echo "..." | coord send` é decodificado em cp1252 e
    #    vira MOJIBAKE no .md. Evita ter de exportar PYTHONIOENCODING.
    for s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

def _ensure():
    for d in (MSG, STA, STT):
        os.makedirs(d, exist_ok=True)

# ---------- salas ----------
def _read_cwd_file(fn):
    p = os.path.join(os.getcwd(), fn)
    return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else None

def room_name_from(args):
    if getattr(args, "room", None):
        return args.room
    if os.environ.get("COORD_ROOM"):
        return os.environ["COORD_ROOM"]
    return _read_cwd_file(".coordroom")

def room_dir_for(name):
    return os.path.join(ROOMS_BASE, name)

def bind_room(args, silent=False):
    """Resolve a sala ATIVA e seta os globals. Retorna o dir, ou None se não vinculada."""
    name = room_name_from(args)
    if name:
        if not ROOM_RE.match(name):
            if silent: return None
            sys.exit(f"erro: nome de sala inválido '{name}' (letras/números/.-_, até 64).")
        _set_room(room_dir_for(name)); return BASE
    if os.environ.get("COORD_DIR"):              # back-compat: caminho direto de sala
        _set_room(os.environ["COORD_DIR"]); return BASE
    return None

def _register_member(name, cwd=None):
    # Registra (ou atualiza) o membro na sala ativa: nome + pasta + sessão + ts.
    # É o que `rooms`/`state` usam pra listar "quem está em qual pasta".
    try:
        d = os.path.join(STA, "members"); os.makedirs(d, exist_ok=True)
        sess = os.environ.get("CLAUDE_CODE_SESSION_ID", "?")
        with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"name={name}\ncwd={cwd or os.getcwd()}\nsession={sess}\nts={int(time.time()*1000)}\n")
    except Exception:
        pass

def _read_file(p):
    return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else None

# ---------- hierarquia de salas (DAG: aresta sala->pai) ----------
def _parent_path(room):
    return os.path.join(ROOMS_BASE, room, "state", "parent")

def _read_parent(room):
    return _read_file(_parent_path(room))

def _is_ancestor(anc, room):
    # True se 'anc' é ancestral de 'room' (subindo pelos parents). Guarda contra ciclo pré-existente.
    seen, cur = set(), room
    while cur and cur not in seen:
        seen.add(cur)
        cur = _read_parent(cur)
        if cur == anc:
            return True
    return False

def _room_members(room):
    d = os.path.join(ROOMS_BASE, room, "state", "members")
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            info = {"name": f}
            try:
                for line in open(os.path.join(d, f), encoding="utf-8"):
                    if "=" in line:
                        k, _, v = line.partition("="); info[k.strip()] = v.strip()
            except Exception:
                pass
            out.append(info)
    return out

# ---------- identidade ----------
def _existing_me():
    return _read_cwd_file(".coordme")

def _me_safe(args):
    # como me_from, mas NUNCA sai (pro hook/wake silencioso).
    return getattr(args, "me", None) or os.environ.get("COORD_ME") or _existing_me()

def me_from(args):
    if getattr(args, "me", None):
        return args.me
    if os.environ.get("COORD_ME"):
        return os.environ["COORD_ME"]
    p = os.path.join(os.getcwd(), ".coordme")
    if os.path.isfile(p):
        return open(p, encoding="utf-8").read().strip()
    sys.exit("erro: não sei quem você é. Rode `coord join <sala> --as <nome>` ou passe --me <nome>.")

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

# cursor de WAKE: separado do de leitura. Marca o que já foi *surfaceado* pelo
# auto-wake (hook Stop), pra cada mensagem acordar o agente no máximo 1x — sem
# isso o hook re-bloquearia o stop em loop. Independe de `read` (a msg segue
# "não lida" no inbox até o agente realmente ler).
def wake_cursor(name):
    f = os.path.join(STA, f"wake-{name}")
    return int(open(f).read().strip()) if os.path.isfile(f) else None

def set_wake_cursor(name, ms):
    _ensure()
    open(os.path.join(STA, f"wake-{name}"), "w").write(str(ms))

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
    # newline="\n": NÃO deixa o text-mode do Windows converter \n->\r\n. Sem isso os .md
    # ficam CRLF no disco e um leitor externo (ex: o dashboard) quebra no split "\n\n".
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    os.replace(tmp, final)              # rename atômico -> nunca half-write
    feed = f"FROM={de} TO={para} TYPE={tipo} STATUS={status} ID={mid} SUBJ={assunto}\n"
    with open(FEED, "a", encoding="utf-8", newline="\n") as fh:  # append pequeno = atômico
        fh.write(feed)
    _register_member(de)                # mantém a pasta/sessão do agente atualizada
    return mid, ms

# ---------- comandos: salas ----------
def _do_join(room, name, modifies=None, reserves=None, body=None):
    if not room or not ROOM_RE.match(room):
        sys.exit(f"erro: nome de sala inválido '{room}' (letras/números/.-_, até 64).")
    if not name:
        sys.exit("erro: informe a identidade. use: coord join <sala> --as <nome>")
    cwd = os.getcwd()
    open(os.path.join(cwd, ".coordroom"), "w", encoding="utf-8").write(room)  # vincula a sala ao projeto
    open(os.path.join(cwd, ".coordme"),   "w", encoding="utf-8").write(name)
    _set_room(room_dir_for(room)); _ensure()
    text = body or ""
    extra = []
    if modifies: extra.append(f"**Modifico:** {modifies}")
    if reserves: extra.append(f"**Reservo p/ outros:** {reserves}")
    if extra: text = (text + "\n\n" + "\n".join(extra)).strip()
    if not text:
        text = f"Sou **{name}**. Entrando na sala '{room}'."
    mid, _ = write_msg(name, "todos", "aviso", f"identidade: {name}", text, status="informativa")
    set_wake_cursor(name, int(time.time() * 1000))   # entra sem despejar histórico no auto-wake
    print(f"ok: '{name}' vinculado à sala '{room}'  (./.coordme + ./.coordroom)  |  intro {mid}")

def c_join(a):
    _do_join(a.room_name, a.as_ or _existing_me(), a.modifies, a.reserves, a.body)

def c_init(a):   # back-compat: agora exige sala
    if not getattr(a, "room", None):
        sys.exit("erro: agora toda identidade entra numa SALA.\n"
                 "      use: coord join <sala> --as <nome>   (veja `coord rooms`)\n"
                 "      ou:  coord init <nome> --room <sala>")
    _do_join(a.room, a.name, a.modifies, a.reserves, a.body)

def c_rooms(a):
    cur = room_name_from(a)
    rooms = sorted(d for d in os.listdir(ROOMS_BASE)
                   if os.path.isdir(os.path.join(ROOMS_BASE, d))) if os.path.isdir(ROOMS_BASE) else []
    if not rooms:
        print(f"nenhuma sala em {ROOMS_BASE}.")
        print("crie/entre com: coord join <sala> --as <nome>")
        if cur: print(f'(seu cwd está marcado p/ a sala "{cur}", ainda vazia)')
        return
    print(f"salas em {ROOMS_BASE}:")
    for r in rooms:
        ms = _room_members(r)
        mark = "   <- você está aqui" if r == cur else ""
        print(f'  {r}  [{len(ms)} agente(s)]{mark}')
        for m in ms:
            print(f'      - {m.get("name","?")}  ({m.get("cwd","?")})')
    if cur and cur not in rooms:
        print(f'(seu cwd está marcado p/ a sala "{cur}", ainda sem mensagens)')

def c_room(a):
    name = room_name_from(a); me = _existing_me()
    if not name:
        print("nenhuma sala vinculada neste cwd.")
        print("rode `coord rooms` e `coord join <sala> --as <nome>`.")
        return
    print(f"sala: {name}" + (f"  |  você: {me}" if me else "  |  (sem identidade — use --as no join)"))

def _room_state(room):
    # Estado de UMA sala p/ o DAG. Ativa a sala pra reusar all_msgs/parse/eff_status/cursor.
    _set_room(room_dir_for(room))
    parsed = [parse(p) for p in all_msgs()]
    openq = sum(1 for m in parsed
                if m.get("TIPO") == "pergunta" and eff_status(m["ID"], m.get("STATUS", "")) == "aberta")
    members = _room_members(room)
    for mem in members:
        nm = mem.get("name", "")
        cur = cursor(nm)
        mem["last_seen_ts"] = mem.get("ts")
        mem["unread_count"] = sum(1 for m in parsed
                                  if m["_ms"] > cur and m.get("DE") != nm and m.get("PARA") in (nm, "todos"))
    return {
        "name": room,
        "parent": _read_parent(room),                 # aresta sala->pai (DAG); None = raiz
        "members": members,
        "message_count": len(parsed),
        "created_ts": min((m["_ms"] for m in parsed), default=None),
        "last_activity_ts": max((m["_ms"] for m in parsed), default=None),
        "open_questions": openq,
    }

def c_state(a):
    # Saída machine-readable p/ o dashboard renderizar o DAG.
    # Nós = salas + pastas (member.cwd); arestas = membro->sala e sala->parent.
    # subrooms o cliente deriva agrupando por 'parent'. (--json é no-op: já é sempre JSON.)
    import json
    rooms = []
    if os.path.isdir(ROOMS_BASE):
        for r in sorted(os.listdir(ROOMS_BASE)):
            if os.path.isdir(os.path.join(ROOMS_BASE, r)):
                rooms.append(_room_state(r))
    print(json.dumps({"rooms_base": ROOMS_BASE, "rooms": rooms}, ensure_ascii=False))

def c_messages(a):
    # JSON das mensagens da sala ativa (--room <sala>) — desacopla o viewer do dashboard
    # do parse dos .md. Status é o EFETIVO (override aplicado). Requer sala vinculada.
    import json
    out = []
    for p in all_msgs():
        m = parse(p)
        out.append({
            "id": m.get("ID"), "de": m.get("DE"), "para": m.get("PARA"),
            "tipo": m.get("TIPO"), "status": eff_status(m["ID"], m.get("STATUS", "")),
            "ref": m.get("REF"), "assunto": m.get("ASSUNTO"),
            "ts": m["_ms"], "body": m["_body"],
        })
    print(json.dumps({"room": room_name_from(a), "messages": out}, ensure_ascii=False))

# ---------- mutações (chamadas pelo server do dashboard via CLI; exit!=0 + stderr em erro) ----------
def _member_file(room, name):
    return os.path.join(ROOMS_BASE, room, "state", "members", name)

def _link_folder(path, room, name):
    open(os.path.join(path, ".coordroom"), "w", encoding="utf-8", newline="\n").write(room)
    open(os.path.join(path, ".coordme"),   "w", encoding="utf-8", newline="\n").write(name)
    _set_room(room_dir_for(room)); _ensure(); _register_member(name, cwd=path)

def c_link(a):
    path = os.path.abspath(a.path)
    room = a.room_name
    if not ROOM_RE.match(room): sys.exit(f"erro: nome de sala inválido '{room}'.")
    if not os.path.isdir(path): sys.exit(f"erro: pasta não existe: {path}")
    name = a.as_ or _read_file(os.path.join(path, ".coordme")) or os.path.basename(path.rstrip("/\\")) or "agente"
    _link_folder(path, room, name)
    print(f"ok: pasta '{path}' linkada à sala '{room}' como '{name}'")

def c_unlink(a):
    path = os.path.abspath(a.path)
    room = _read_file(os.path.join(path, ".coordroom"))
    name = _read_file(os.path.join(path, ".coordme"))
    if not room:
        sys.exit(f"erro: pasta '{path}' não está linkada a nenhuma sala.")
    cr = os.path.join(path, ".coordroom")
    if os.path.isfile(cr): os.remove(cr)
    if name and os.path.isfile(_member_file(room, name)):
        os.remove(_member_file(room, name))     # some do DAG
    print(f"ok: pasta '{path}' deslinkada da sala '{room}'")

def c_move(a):
    path = os.path.abspath(a.path)
    room = a.room_name
    if not ROOM_RE.match(room): sys.exit(f"erro: nome de sala inválido '{room}'.")
    if not os.path.isdir(path): sys.exit(f"erro: pasta não existe: {path}")
    old = _read_file(os.path.join(path, ".coordroom"))
    name = _read_file(os.path.join(path, ".coordme")) or os.path.basename(path.rstrip("/\\")) or "agente"
    if old and old != room and os.path.isfile(_member_file(old, name)):
        os.remove(_member_file(old, name))
    _link_folder(path, room, name)
    print(f"ok: '{name}' movido {old or '(nenhuma)'} -> '{room}'")

def c_nest(a):
    sala, pai = a.sala, a.pai
    if not ROOM_RE.match(sala) or not ROOM_RE.match(pai): sys.exit("erro: nome de sala inválido.")
    if sala == pai: sys.exit("erro: uma sala não pode ser pai de si mesma.")
    if not os.path.isdir(room_dir_for(sala)): sys.exit(f"erro: sala '{sala}' não existe.")
    if not os.path.isdir(room_dir_for(pai)):  sys.exit(f"erro: sala pai '{pai}' não existe.")
    if _is_ancestor(sala, pai):               # pai é descendente de sala -> ciclo
        sys.exit(f"erro: ciclo — '{sala}' já é ancestral de '{pai}'. O DAG deve ser acíclico.")
    d = os.path.join(room_dir_for(sala), "state"); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "parent"), "w", encoding="utf-8", newline="\n").write(pai)
    print(f"ok: sala '{sala}' aninhada sob '{pai}'")

def c_unnest(a):
    p = _parent_path(a.sala)
    if os.path.isfile(p):
        os.remove(p); print(f"ok: sala '{a.sala}' agora é raiz (sem pai)")
    else:
        print(f"(sala '{a.sala}' já era raiz)")

# ---------- comandos ----------

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

def _stat_key(path):
    try:
        st = os.stat(path)
        return (st.st_dev, st.st_ino)          # detecta troca de arquivo (rotação)
    except OSError:
        return None

def c_watch(a):
    # Tail nativo em Python: NÃO depende de bash/tail/grep e funciona com caminho
    # Windows (o `bash -c 'tail -F "C:\...\feed.log"'` antigo morria: o tail do
    # git-bash não abria o path com backslash, o erro ia pro 2>/dev/null e o pipe
    # fechava -> banner + "stream ended"). Self filtrado, flush por linha.
    me = me_from(a)
    _ensure()
    if not os.path.isfile(FEED):
        open(FEED, "a", encoding="utf-8").close()
    prefix = f"FROM={me} "
    print(f"[watch] {me}: ouvindo feed, ignorando self. Ctrl-C p/ sair.", flush=True)
    f = open(FEED, "rb")                         # binário: tell() = offset real em bytes
    f.seek(0, os.SEEK_END)                       # tail -n 0: só mensagens novas
    key = _stat_key(FEED)
    try:
        while True:
            pos = f.tell()
            raw = f.readline()
            if raw and raw.endswith(b"\n"):       # linha completa
                line = raw.decode("utf-8", "replace")
                if not line.startswith(prefix):   # filtra self
                    sys.stdout.write(line)
                    sys.stdout.flush()
                continue
            if raw:
                f.seek(pos)                       # linha parcial: rebobina até completar
            time.sleep(1.0)                       # sem dados: poll + checa rotação
            try:
                rotated = _stat_key(FEED) != key or os.path.getsize(FEED) < f.tell()
            except OSError:
                rotated = False                   # feed sumiu momentaneamente
            if rotated:
                try:
                    f.close()
                except Exception:
                    pass
                f = open(FEED, "rb")              # segue o novo arquivo desde o início
                key = _stat_key(FEED)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            f.close()
        except Exception:
            pass

def c_wake(a):
    # Auto-wake (chamado pelo hook Stop). Imprime mensagens NOVAS dirigidas a mim
    # desde o último wake e avança o cursor de wake. Stdout vazio = nada novo.
    # Primeira vez (sem cursor): prima em "agora" e não despeja histórico
    # (semântica tail -n 0); o backstop de histórico é o hook UserPromptSubmit.
    me = _me_safe(a)
    if not me:                  # sem identidade -> hook fica silencioso
        return
    cur = wake_cursor(me)
    if cur is None:
        set_wake_cursor(me, int(time.time() * 1000))
        return
    new = []
    for p in all_msgs():
        m = parse(p)
        if m["_ms"] <= cur: continue
        if m.get("DE") == me: continue
        if m.get("PARA") not in (me, "todos"): continue
        new.append(m)
    if not new:
        return
    set_wake_cursor(me, max(m["_ms"] for m in new))
    print(f"📨 coord: {len(new)} mensagem(ns) nova(s) para {me}:")
    for m in new:
        print("  " + _fmt_line(m))

def c_whoami(a):
    print(me_from(a))

def c_help(a):
    print(textwrap.dedent("""\
    coord - coordenação entre agentes Claude (conflict-free, token-mínimo)

    SALAS são separadas — você só fala na sala em que entrou. Sem sala vinculada,
    send/inbox/wake recusam (nada vaza p/ esforço alheio).

      rooms            lista as salas + agentes e a PASTA de cada um
      join <sala> --as <nome> [--modifies "X,Y"] [--reserves "Z"] [--body "..."]
            entra/cria a sala, vincula ao projeto (./.coordme + ./.coordroom), posta intro.
      room             mostra a sala vinculada a este cwd
      state            JSON do DAG (salas+membros+métricas+hierarquia) — p/ o dashboard
      messages --room <sala>   JSON das mensagens da sala (viewer sem parsear .md)
      link <pasta> <sala> [--as <nome>]   liga uma pasta a uma sala (dnd)
      unlink <pasta>                      tira a pasta da sala
      move <pasta> <sala>                 move a pasta p/ outra sala
      nest <sala> <pai> | unnest <sala>   hierarquia sala->sala (DAG, sem ciclo)
      init <nome> --room <sala> [...]            alias de join (compat)
      send --to <nome|todos> --type <aviso|pergunta|resposta|decisao|bloqueio>
           --subject "..." [--ref ID] [--status ...] [--body "..." | stdin]
      inbox            lista não lidas (não consome)
      read [ID]        abre msg(s); sem ID = todas não lidas + marca lido
      open             perguntas abertas dirigidas a você
      answer <ID> [--to X] [--body "..."|stdin]   responde E fecha a pergunta
      watch            tail nativo do feed da sala (rodar como background task)
      wake             [hook Stop] surfaceia msgs novas pra mim e avança cursor de wake
      whoami / help

    Identidade: --me NAME | $COORD_ME | ./.coordme
    Sala:       --room NAME | $COORD_ROOM | ./.coordroom | $COORD_DIR (path direto)
                dirs sob $COORD_ROOMS_BASE (default ~/.claude/coord-rooms/<sala>)
    """))

def main():
    _utf8_io()
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--me")
    p.add_argument("--room")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("rooms"); s.set_defaults(fn=c_rooms)
    s = sub.add_parser("room"); s.set_defaults(fn=c_room)
    s = sub.add_parser("state"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=c_state)
    s = sub.add_parser("messages"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=c_messages)
    # mutações do DAG (drag-and-drop do dashboard via CLI)
    s = sub.add_parser("link"); s.add_argument("path"); s.add_argument("room_name"); s.add_argument("--as", dest="as_")
    s.set_defaults(fn=c_link)
    s = sub.add_parser("unlink"); s.add_argument("path"); s.set_defaults(fn=c_unlink)
    s = sub.add_parser("move"); s.add_argument("path"); s.add_argument("room_name"); s.set_defaults(fn=c_move)
    s = sub.add_parser("nest"); s.add_argument("sala"); s.add_argument("pai"); s.set_defaults(fn=c_nest)
    s = sub.add_parser("unnest"); s.add_argument("sala"); s.set_defaults(fn=c_unnest)

    s = sub.add_parser("join"); s.add_argument("room_name")
    s.add_argument("--as", dest="as_"); s.add_argument("--modifies"); s.add_argument("--reserves"); s.add_argument("--body")
    s.set_defaults(fn=c_join)

    s = sub.add_parser("init"); s.add_argument("name")
    s.add_argument("--room"); s.add_argument("--modifies"); s.add_argument("--reserves"); s.add_argument("--body")
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
    s = sub.add_parser("wake"); s.set_defaults(fn=c_wake)
    s = sub.add_parser("whoami"); s.set_defaults(fn=c_whoami)
    s = sub.add_parser("help"); s.set_defaults(fn=c_help)

    a = p.parse_args()
    cmd = getattr(a, "cmd", None)
    if not cmd:
        c_help(a); return
    # comandos que tocam uma sala: precisam de sala vinculada (senão recusam / no-op p/ wake)
    if cmd in {"send", "inbox", "read", "open", "answer", "watch", "wake", "messages"}:
        silent = (cmd == "wake")
        if bind_room(a, silent=silent) is None:
            if silent:
                return                       # hook fica silencioso quando não há sala
            sys.exit("erro: nenhuma sala vinculada neste projeto.\n"
                     "      rode `coord rooms` e `coord join <sala> --as <nome>` primeiro.")
    a.fn(a)

if __name__ == "__main__":
    main()
