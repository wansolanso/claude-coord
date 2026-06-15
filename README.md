# claude-coord

Plugin do Claude Code para **coordenação entre múltiplos agentes Claude** (várias sessões
trabalhando no mesmo projeto ou em projetos diferentes na mesma máquina).

Mensagens trocadas via arquivos locais, em **salas separadas** (uma por esforço/projeto —
esforços diferentes ficam isolados) — **conflict-free** (cada mensagem é um arquivo próprio,
vários Claudes escrevem ao mesmo tempo sem colidir, sem lock) e **token-mínimo** (tudo por
comando curto). Recebimento em 2 camadas: hook `Stop` (auto-wake, sessão ativa) + watcher
`coord watch` (Monitor, acorda também sessão ociosa — recomendado p/ agente autônomo).

## Componentes

| Parte | O quê |
|---|---|
| Skill `coord` | porta de entrada auto-descoberta pelo Claude (gatilhos: "handoff", "coordene com outro claude", etc.) |
| `scripts/coord.py` | o engine (CLI: `rooms join room send inbox read open answer watch wake`) — Python puro, sem deps |
| `scripts/coord` | launcher portável que acha o Python (`python3`/`python`/`py`) sozinho |
| Hook `SessionStart` | sincroniza launcher + engine para `~/.claude/coord-bin/` (caminho portável) |
| Hook `UserPromptSubmit` | injeta aviso quando há mensagens não lidas (fail-safe, custo 0 token quando ocioso) |
| Hook `Stop` | auto-wake: ao fim do turno entrega msgs novas — cobre sessão ATIVA, custo 0 token. NÃO acorda sessão ociosa (sem turno) → use `coord watch` |
| `coord watch` | watcher (Monitor) que acorda também a sessão OCIOSA — recomendado p/ agente autônomo que coordena |

## Instalação em outra máquina

Requisitos: só Python 3 (o engine é Python puro, sem deps — o watcher não precisa mais de `bash`/`tail`).

```bash
claude plugin marketplace add wansolanso/claude-coord
claude plugin install coord@claude-coord
```
Reinicie a sessão (ou `/reload-plugins`). Pronto — o skill `coord` aparece sozinho.

## Uso (resumo)

```bash
ENGINE=~/.claude/coord-bin/coord                 # launcher acha o Python sozinho
$ENGINE rooms                                    # lista salas + a pasta de cada agente
$ENGINE join minha-sala --as meu-nome --modifies "o que toco"   # 1x por projeto
$ENGINE watch &                                  # watcher (Monitor): acorda mesmo ocioso — RODE se for agente autônomo
# (sessão ativa também recebe via hook Stop; o watch é o que cobre a sessão ociosa)
$ENGINE send --to todos --type aviso --subject "..." --body "..."   # só alcança a sala
$ENGINE inbox        # não lidas
$ENGINE read         # lê tudo novo
$ENGINE answer "assunto" --body "..."            # responde e fecha
```

**Salas são entidades separadas** — cada uma um diretório sob `~/.claude/coord-rooms/<sala>`.
Dois Claudes só se enxergam na **mesma sala**, e `--to todos` só alcança quem está nela.
**Sem sala vinculada, `send`/`inbox`/`wake` recusam** (nada vaza pra esforço alheio): rode
`rooms` e `join` primeiro. Vínculo gravado em `./.coordroom` (override: `--room`/`$COORD_ROOM`).

Detalhes completos: ver `SKILL.md`.

## Modelo recomendado

Para agentes headless autônomos que coordenam, use **`sonnet` ou superior** — `haiku` não
seguiu o protocolo reativo de forma confiável em teste real.
