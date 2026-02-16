# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Hub is a lightweight Python web server that exposes Claude Code CLI sessions on a mobile browser via Tailscale. It manages multiple persistent sessions using tmux and serves web terminals through ttyd.

**Stack**: Python 3 (stdlib only, zero dependencies) + ttyd + tmux + Tailscale

## Architecture

```
iPhone/Safari  ←── Tailscale ──→  Mac
                                   ├── :7680  claude-hub.py (HTTP dashboard)
                                   └── :77xx  ttyd → tmux → claude (per session)
```

- `claude-hub.py` — HTTP server (stdlib `http.server`). Config, helpers, session management, HTTP handler, CLI.
- `templates/hub.html` — Dashboard HTML/CSS/JS. Placeholders: `{{SESSION_CARDS}}`, `{{COUNT_TEXT}}`.
- `templates/terminal.html` — Terminal wrapper HTML/CSS/JS with 2-row virtual keyboard. Placeholders: `{{SESSION_NAME}}`, `{{TERMINAL_URL}}`.
- `install.sh` — Setup script that installs dependencies (ttyd, tmux via Homebrew), creates a macOS LaunchAgent for autostart, and generates a `ctl.sh` control script at `~/.claude-hub/`.

### Key code sections in `claude-hub.py`

- **Config** (top): Environment variables, port ranges (7700-7799), paths
- **Helpers**: `_load_template()` (loads HTML from `templates/` with cache), `port_for_name()` (deterministic port from session name hash), `get_sessions()` (lists tmux sessions), `start_session()` / `stop_session()`
- **HTML Rendering**: `render_hub()` loads `templates/hub.html` and replaces placeholders. `render_terminal()` loads `templates/terminal.html` and replaces placeholders.
- **HTTP Handler**: `HubHandler(BaseHTTPRequestHandler)` with routes: `/`, `/start/{name}`, `/stop/{name}`, `/terminal/{name}`, `/api/sessions`, `/api/ttyd-ready/{name}`, `/api/send-keys/{name}`, `/api/send-text/{name}`, `/api/scroll/{name}`, `/api/folders`
- **Main**: Server startup with signal handling
- **CLI**: `cmd_start()`, `cmd_stop()`, `cmd_status()` — subcommands for service control

## Deployment Workflow

After editing files, always deploy with:

```bash
# 1. Copy to production dir
cp claude-hub.py ~/.claude-hub/claude-hub.py
cp templates/*.html ~/.claude-hub/templates/

# 2. Kill existing ttyd processes (they keep old config)
pkill -f "ttyd.*-p 77"

# 3. Restart the hub
~/.claude-hub/ctl.sh restart
```

The `ctl.sh` script supports: `start`, `stop`, `restart`, `status`, `logs`, `uninstall`.

Production files live at `~/.claude-hub/` (created by `install.sh`).

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_HUB_PORT` | `7680` | Dashboard port |
| `CLAUDE_FONT_SIZE` | `11` | Terminal font size (xterm.js) |
| `TTYD_BIN` | `/opt/homebrew/bin/ttyd` | ttyd binary path |
| `CLAUDE_BIN` | `claude` | Claude CLI path |
| `CLAUDE_DEV_ROOT` | `~/Desenvolvimento` | Root dir for folder picker |

## iOS/Safari Considerations

- **HTTPS obrigatório**: Safari iOS bloqueia WebSocket (ws://) cross-origin em iframes silenciosamente. HTTPS/WSS via certificados Tailscale (`tailscale cert`) resolve 100%.
- **ttyd renderer**: DOM renderer via custom `ttyd-index.html` (`-I` flag). WebGL não renderiza em iframes no iOS Safari. A flag `-t rendererType=dom` do ttyd é ignorada — precisa patchear o JS bundled diretamente.
- **Google Fonts**: Removido de TODAS as páginas (render-blocking, adiciona segundos de delay no mobile). Usa fontes do sistema (`SF Mono`, `Menlo`, `-apple-system`).
- **iOS redirect**: iOS Safari é redirecionado diretamente para o ttyd URL (sem iframe) com parâmetros via URL hash (`#hub=...&session=...`).
- **Custom ttyd-index.html** (`~/.claude-hub/ttyd-index.html`): topbar com botão voltar, teclado virtual com teclas especiais (Esc, PgUp/PgDn, setas, Ctrl combos, Colar), viewport meta para mobile.

## Important Notes

- macOS only (uses LaunchAgents via launchd)
- ttyd version: 1.7.7
- No tests, no linter, no build step configured
- HTML/CSS/JS dos templates fica em `templates/` — `claude-hub.py` carrega com `_load_template()` (cache em memória)
- `ttyd-index.html` (~715KB) contém JS bundled do ttyd + HTML/CSS custom — editar com Python script ou sed
- Session names map deterministically to ports via `hashlib.md5` em `port_for_name()`
- HTTPS via Tailscale certs (Let's Encrypt para `*.ts.net`). SSL context com ciphers ECDHE+AESGCM/CHACHA20
- ThreadedHTTPServer (ThreadingMixIn) para requests paralelos
- Security: Tailscale network isolation + HTTPS
