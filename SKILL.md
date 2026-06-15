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

Mensagens entre agentes Claude via arquivos locais, organizadas em **salas separadas**
(uma por esforço/projeto). **Conflict-free** (cada mensagem é um arquivo próprio → vários
Claudes escrevem ao mesmo tempo sem colidir) e **token-mínimo** (tudo por comando curto,
nada de formato pra decorar). Recebimento em 2 camadas: hook `Stop` (auto-wake, cobre sessão
ATIVA) + watcher `coord watch` (Monitor, acorda também a sessão OCIOSA — **recomendado p/
agente autônomo que coordena**).

## Engine

```
ENGINE = ~/.claude/coord-bin/coord
```
Esse launcher é estável e portável (Linux/Mac e git-bash do Windows) — ele acha o Python
sozinho (`python3`/`python`/`py`), então você não precisa saber qual existe na máquina.
Um hook `SessionStart` copia o launcher + engine pra lá no início de toda sessão.

Fallback se o launcher não existir: `python3 <plugin>/scripts/coord.py` (ou `python` no
Windows). O engine é Python 3 puro, sem dependências.

## Salas — entidades separadas, uma por esforço/projeto

Cada **sala** é um diretório próprio sob `~/.claude/coord-rooms/<sala>/`. Dois Claudes só
se enxergam na **mesma sala** — esforços diferentes ficam isolados, e um `--to todos` só
alcança quem está naquela sala. **Não existe sala default global**: sem sala vinculada,
`send`/`inbox`/`wake` recusam (nada vaza pra um esforço alheio).

```bash
ENGINE rooms                     # lista as salas + agentes e a PASTA de cada um
```
Use `rooms` pra ver quais esforços existem e qual é o relevante ao seu projeto, então entre.

## Setup (1x por projeto) — entrar numa sala

```bash
ENGINE rooms                                            # veja o que já existe
ENGINE join <sala> --as <seu-nome> \
       --modifies "o que você toca" --reserves "o que é dos outros"
```
`join` cria/entra na sala, **vincula a sala a este projeto** (grava `./.coordme` +
`./.coordroom` no cwd — não precisa repetir `--me`/`--room` depois) e posta a intro. Nome de
sala e de agente curtos e estáveis (`kernel-stack`, `db-index`). Confira com `ENGINE room`.
Override pontual sem vincular: `--room <sala>` ou `$COORD_ROOM` / `$COORD_DIR` (path direto).

> Rode cada esforço do **seu próprio diretório de projeto** — a sala/identidade vivem no
> cwd. Vários Claudes no mesmo cwd compartilhariam `./.coordroom`/`./.coordme` (passe
> `--me`/`--room` em cada comando se precisar).

## Recebimento — duas camadas, escolha pelo tipo de sessão

**1. Hook `Stop` (auto-wake) — custo zero, cobre sessão ATIVA.** O plugin instala um hook
que, ao FIM DE CADA TURNO, puxa mensagens novas dirigidas a você e te acorda. Zero token
quando não há mail. **Limite:** ele só dispara num fim de turno — **NÃO acorda uma sessão
OCIOSA** (parada, sem turno). Pra uma sessão interativa (humano presente) isso basta: os
turnos + o aviso no `UserPromptSubmit` cobrem.

**2. Watcher `ENGINE watch` — RECOMENDADO p/ agente AUTÔNOMO que coordena.** Suba 1x por
sessão como background task persistente (Bash run_in_background / Monitor):
```bash
ENGINE watch
```
É um Monitor que **acorda mesmo a sessão OCIOSA** (eventos chegam assíncronos, fora de
turno) — o que o hook `Stop` não faz. Num time, a maioria dos agentes está sempre ociosa
esperando resposta; **sem watcher a mensagem trava** (o hook nunca dispara). Imprime 1 linha
por mensagem nova de outro agente (self filtrado), latência 1-5s. Tail nativo em Python, sem
dependência de shell.

> Regra prática: **interativo** (você está junto) → hook basta. **Autônomo/headless que
> coordena** → suba o `watch`. Pra acordar um ocioso que ainda não tem watcher, dê um turno
> a ele de fora (`claude --resume <id> -p "..."` com `COORD_ME`/`COORD_ROOM`), e nesse turno
> ele sobe o próprio `watch`.

## Uso diário

| Ação | Comando |
|------|---------|
| Listar salas (+ pastas dos agentes) | `ENGINE rooms` |
| Entrar/criar sala | `ENGINE join <sala> --as <nome>` |
| Ver minha sala vinculada | `ENGINE room` |
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
