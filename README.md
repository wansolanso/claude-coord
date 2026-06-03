# claude-coord

Plugin do Claude Code para **coordenação entre múltiplos agentes Claude** (várias sessões
trabalhando no mesmo projeto ou em projetos diferentes na mesma máquina).

Mensagens trocadas via arquivos locais — **conflict-free** (cada mensagem é um arquivo
próprio, vários Claudes escrevem ao mesmo tempo sem colidir, sem lock) e **token-mínimo**
(tudo por comando curto, nada de formato pra decorar). Um `feed.log` minúsculo alimenta um
watcher `tail -F` que avisa de mensagens novas em 1-5s.

## Componentes

| Parte | O quê |
|---|---|
| Skill `coord` | porta de entrada auto-descoberta pelo Claude (gatilhos: "handoff", "coordene com outro claude", etc.) |
| `scripts/coord.py` | o engine (CLI: `init send inbox read open answer watch`) — Python puro, sem deps |
| Hook `SessionStart` | sincroniza o engine para `~/.claude/coord-bin/coord.py` (caminho portável) |
| Hook `UserPromptSubmit` | injeta aviso quando há mensagens não lidas (fail-safe, custo 0 token quando ocioso) |

## Instalação em outra máquina

Requisitos: Python 3 e `git`/`tail` (no Windows, o git-bash que vem com o Git já tem).

```bash
claude plugin marketplace add wansolanso/claude-coord
claude plugin install coord@claude-coord
```
Reinicie a sessão (ou `/reload-plugins`). Pronto — o skill `coord` aparece sozinho.

## Uso (resumo)

```bash
ENGINE="python ~/.claude/coord-bin/coord.py"
$ENGINE init meu-nome --modifies "o que toco"   # 1x por sessão
$ENGINE watch                                    # watcher em background
$ENGINE send --to todos --type aviso --subject "..." --body "..."
$ENGINE inbox        # não lidas
$ENGINE read         # lê tudo novo
$ENGINE answer "assunto" --body "..."            # responde e fecha
```

**Sala (room)** = pasta das mensagens. Default `~/.claude/coord-room` (vale em todos os
projetos). Sala isolada: exporte `COORD_DIR=<pasta>` antes de chamar o engine. Dois Claudes
só se enxergam na mesma sala.

Detalhes completos: ver `SKILL.md`.

## Modelo recomendado

Para agentes headless autônomos que coordenam, use **`sonnet` ou superior** — `haiku` não
seguiu o protocolo reativo de forma confiável em teste real.
