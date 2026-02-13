<p align="center">
  <img src="icon_chub.png" width="120" alt="Claude Hub">
</p>

<h1 align="center">Claude Hub</h1>

<p align="center">
  <strong>Acesse o Claude Code pelo celular.</strong><br>
  Terminal completo no iPhone via Tailscale — sem servidor, sem nuvem, tudo local.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-orange?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/macOS-only-black?style=flat-square&logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/tailscale-private%20network-0082C9?style=flat-square&logo=tailscale&logoColor=white" alt="Tailscale">
  <img src="https://img.shields.io/badge/zero-dependencies-green?style=flat-square" alt="Zero deps">
</p>

---

## O que é

Um servidor web leve que roda no seu Mac e expõe sessões do [Claude Code](https://claude.ai/code) no browser do celular. Cada sessão é um terminal real com tmux persistente — pode fechar o browser, e quando voltar, tudo continua lá.

```
┌──────────┐                         ┌─────────────────────────┐
│  iPhone   │ ◄── Tailscale (VPN) ──► │  Mac                    │
│  Safari   │     rede privada        │                         │
└──────────┘                         │  :7680  Dashboard (web) │
                                      │  :77xx  ttyd → tmux     │
                                      │              └─ claude   │
                                      └─────────────────────────┘
```

## Features

- **Dashboard mobile-first** — interface dark otimizada pra telas pequenas
- **Sessões persistentes** — tmux mantém tudo rodando, mesmo com o browser fechado
- **Teclado virtual** — teclas especiais (Esc, Ctrl+C, PgUp, setas, Tab) direto na tela
- **Múltiplas sessões** — cada uma com nome, pasta e porta dedicados
- **Folder picker** — escolha o diretório de trabalho ao criar a sessão
- **HTTPS nativo** — certificados Tailscale (Let's Encrypt) para WebSocket confiável
- **Zero dependências Python** — usa apenas stdlib
- **Instala em 30 segundos** — um script configura tudo, incluindo autostart no boot

## Pré-requisitos

| Dependência | Instalação |
|---|---|
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` |
| **Tailscale** | [tailscale.com/download](https://tailscale.com/download) (Mac + celular) |
| **Homebrew** | O instalador cuida do resto |

## Instalação

```bash
git clone https://github.com/orseni/claude-hub.git
cd claude-hub
bash install.sh
```

O instalador:
1. Instala `ttyd` e `tmux` via Homebrew
2. Configura autostart no boot (launchd)
3. Cria o comando `claude-hub` no terminal

### HTTPS (recomendado)

Para terminal confiável no iOS Safari:

```bash
# Habilite HTTPS no painel do Tailscale (DNS → Enable HTTPS)
tailscale cert macbook-pro.tailnet.ts.net

# Copie os certificados
cp macbook-pro.tailnet.ts.net.crt ~/.claude-hub/hub.crt
cp macbook-pro.tailnet.ts.net.key ~/.claude-hub/hub.key

claude-hub restart
```

## Uso

### No celular

1. Abra `https://seu-mac.tailnet.ts.net:7680` no Safari
2. Toque em **Criar** e escolha a pasta do projeto
3. O terminal do Claude Code abre direto no browser
4. Use o teclado virtual pra teclas especiais

### Dica: atalho na home

No Safari: **Compartilhar → Adicionar à Tela Inicial**. Vira um app com ícone próprio e abre em tela cheia.

### Comandos

```bash
claude-hub start       # Iniciar
claude-hub stop        # Parar
claude-hub restart     # Reiniciar
claude-hub status      # Ver status e sessões ativas
claude-hub logs        # Logs em tempo real
claude-hub uninstall   # Remover tudo
```

## Configuração

Variáveis de ambiente (opcionais):

| Variável | Default | Descrição |
|---|---|---|
| `CLAUDE_HUB_PORT` | `7680` | Porta do dashboard |
| `CLAUDE_FONT_SIZE` | `11` | Tamanho da fonte no terminal |
| `CLAUDE_DEV_ROOT` | `~/Desenvolvimento` | Raiz do folder picker |
| `TTYD_BIN` | `/opt/homebrew/bin/ttyd` | Caminho do ttyd |
| `CLAUDE_BIN` | `claude` | Caminho do Claude CLI |

## Arquitetura

```
~/.claude-hub/
├── claude-hub.py          # Servidor (single-file, ~1700 linhas)
├── ttyd-index.html        # Terminal customizado (DOM renderer + teclado virtual)
├── hub.crt / hub.key      # Certificados HTTPS (Tailscale/Let's Encrypt)
├── ctl.sh                 # Script de controle
├── hub.log                # Stdout
└── hub-error.log          # Stderr
```

**Stack**: Python 3 stdlib + ttyd + tmux + Tailscale. Sem frameworks, sem build, sem frontend separado.

O servidor inteiro é um único arquivo Python que gera HTML/CSS/JS inline. Cada sessão mapeia pra uma porta determinística via hash do nome.

## Segurança

- Acesso restrito à sua **tailnet** do Tailscale (rede privada)
- HTTPS com certificados Let's Encrypt reais (via `tailscale cert`)
- Nenhuma porta exposta na internet
- Sessões rodam com o seu usuário do Mac
- Sem autenticação extra necessária — Tailscale já autentica

## Troubleshooting

<details>
<summary><strong>Servidor não inicia</strong></summary>

```bash
claude-hub logs
cat ~/.claude-hub/hub-error.log
```
</details>

<details>
<summary><strong>Porta em uso</strong></summary>

```bash
lsof -i :7680
kill -9 <PID>
claude-hub restart
```
</details>

<details>
<summary><strong>Terminal cinza no iOS</strong></summary>

Certifique-se que HTTPS está configurado. Safari iOS bloqueia WebSocket (ws://) cross-origin silenciosamente. Com HTTPS/WSS funciona instantaneamente.
</details>

<details>
<summary><strong>Sessão orphan</strong></summary>

```bash
tmux list-sessions          # Ver sessões
tmux kill-session -t nome   # Matar específica
pkill -f "ttyd -p 77"      # Matar ttyd orphans
```
</details>

## Licença

MIT

---

<p align="center">
  Feito pra quem quer usar o Claude Code de qualquer lugar.<br>
  <sub>Powered by ttyd + tmux + Tailscale</sub>
</p>
