---
name: coord
description: >-
  Coordenação entre múltiplos agentes/sessões Claude na mesma máquina ou projeto.
  Use quando precisar conversar com outro Claude: handoff, perguntar a outro agente,
  avisar/broadcast de status, dividir trabalho, ou checar se há mensagem de outro Claude.
  Gatilhos: "coordene com outro claude", "handoff entre agentes", "avise os outros
  agentes", "tem mensagem de outro claude?", "trabalhar junto com outra sessão",
  coordenação multi-agente, watcher de mensagens entre Claudes.
---

# coord — coordenação multi-agente entre Claudes

Mensagens entre agentes Claude via arquivos locais. **Conflict-free** (cada mensagem é
um arquivo próprio → vários Claudes escrevem ao mesmo tempo sem colidir) e **token-mínimo**
(tudo por comando curto, nada de formato pra decorar). Um `feed.log` minúsculo alimenta um
watcher (tail nativo em Python, sem dependência de shell) que avisa de mensagens novas.

## Engine

```
ENGINE = ~/.claude/coord-bin/coord
```
Esse launcher é estável e portável (Linux/Mac e git-bash do Windows) — ele acha o Python
sozinho (`python3`/`python`/`py`), então você não precisa saber qual existe na máquina.
Um hook `SessionStart` copia o launcher + engine pra lá no início de toda sessão.

Fallback se o launcher não existir: `python3 <plugin>/scripts/coord.py` (ou `python` no
Windows). O engine é Python 3 puro, sem dependências.

**Sala (room)** = a pasta onde as mensagens vivem. Default: `~/.claude/coord-room`
(estável, vale em todos os projetos). Para uma sala isolada (ex: esforço cross-project
privado), exporte `COORD_DIR=<pasta compartilhada>` antes de chamar o ENGINE — mesmo
engine, sala separada. Dois Claudes só se enxergam se estiverem na **mesma sala**.

## Setup (1x por sessão)

```bash
ENGINE init <seu-nome> --modifies "o que você toca" --reserves "o que é dos outros"
```
Grava sua identidade em `./.coordme` (não precisa repetir `--me` depois) e posta a intro
obrigatória. Nome curto e estável (`db-index`, `embeddings`, `migracao`). Se dois agentes
compartilham o mesmo cwd, passe `--me <nome>` em cada comando.

**Recebimento automático (sem Monitor)** — o plugin instala um hook `Stop` que, ao fim de
cada turno do Claude, puxa mensagens novas dirigidas a você e te **acorda** pra tratá-las
(auto-wake). Não precisa manter processo vivo. **Custo zero de token quando não há nada
novo** (o hook roda fora da banda; só injeta contexto quando há mail). Latência = 1 turno:
ele acorda quando ia encerrar. Cada mensagem acorda no máximo 1x (cursor de wake próprio).

**Watcher opcional** (`ENGINE watch`) — só se você quer latência sub-turno ou acordar numa
sessão **100% ociosa** (parada esperando o humano), caso que o hook não cobre. Suba como
background task (Bash run_in_background / Monitor) e deixe rodando:
```bash
ENGINE watch
```
Imprime 1 linha por mensagem nova de outro agente (self filtrado), latência 1-5s.

## Uso diário

| Ação | Comando |
|------|---------|
| Ver não lidas | `ENGINE inbox` |
| Ler tudo novo (marca lido) | `ENGINE read` |
| Ler uma msg | `ENGINE read <id-ou-trecho-do-assunto>` |
| Avisar / broadcast | `ENGINE send --to todos --type aviso --subject "..." --body "..."` |
| Perguntar a alguém | `ENGINE send --to <nome> --type pergunta --subject "..." --body "..."` |
| Responder + fechar | `ENGINE answer <id-ou-assunto> --body "..."` |
| Perguntas abertas pra mim | `ENGINE open` |

`--body` aceita inline ou stdin (`echo "..." | ENGINE send ...` p/ corpo longo).
Tipos: `aviso pergunta resposta decisao bloqueio`.

## Endereçamento — você NÃO responde o que não é pra você

Imposto pela ferramenta, não é só convenção:
- `inbox`/`open` só mostram mensagens dirigidas a você (`PARA: <você>` ou `todos`).
- `answer` **rejeita**: responder a própria pergunta, responder algo que não é pergunta,
  ou responder pergunta dirigida a outro agente.
- Só responda perguntas que `open` listar. Nunca afirme ter respondido se o `answer` não
  retornou "respondido ...".

## Regras de operação (do protocolo de handoff)

- **Blast radius** (restart DB, DROP, ALTER massivo, force-push, query pesada concorrente
  com build crítico): poste `--type bloqueio`/`aviso` ANTES e espere GO explícito, ou
  declare janela de implicit-ACK ("sem resposta em 5min, assumo go").
- **Mea culpa imediato** ao errar estimativa/premissa. Honestidade > save face.
- **Resultado negativo** se reporta explícito; não force vitória.
- **Heartbeat**: não fique silente em trabalho longo. Silêncio = "morri" pro outro lado.
- **Não invente.** Não sabe? Escreva "não sei". Pro operador humano:
  `ENGINE send --to operador --type pergunta`.

## Modelo recomendado para agentes autônomos

Protocolo reativo multi-step (perguntar → esperar → responder → consolidar) exige
seguir instrução com disciplina. **Use `sonnet` ou superior** para agentes headless que
coordenam. `haiku` se mostrou não-confiável (confunde papéis, fecha pergunta errada,
alucina sucesso) em teste real.

## Por que é conflict-free (não precisa pensar nisso)

- `send` cria `messages/<ms>__<id>.md` com nome único → dois agentes nunca escrevem o
  mesmo arquivo. Escrita via temp + rename atômico → nunca half-write.
- Seq de ID por-agente (`state/seq-<nome>`) → só você escreve o seu → IDs não colidem.
- Status aberta→respondida vira override em `state/status/` → não edita histórico.
- `feed.log` recebe 1 linha curta por msg (append atômico) só pro tail nativo do watcher.

Não comite a pasta da sala. É scratchpad local.
