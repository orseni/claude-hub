#!/bin/bash
#
# Claude Hub — Instalador
# Acesse o Claude Code do celular via Tailscale
#
# Uso: curl -sL ... | bash
#   ou: bash install.sh
#

set -e

# ── Cores ──
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
DIM='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$HOME/.claude-hub"
HUB_PORT=7680
LABEL="com.claude-hub.server"

info()  { echo -e "${BLUE}ℹ${NC}  $1"; }
ok()    { echo -e "${GREEN}✓${NC}  $1"; }
warn()  { echo -e "${RED}⚠${NC}  $1"; }
step()  { echo -e "\n${BOLD}$1${NC}"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        🤖 Claude Hub — Instalador        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Verificar dependências ──
step "1/5  Verificando dependências..."

# Homebrew
if ! command -v brew &>/dev/null; then
    warn "Homebrew não encontrado. Instalando..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
ok "Homebrew"

# ttyd
if ! command -v ttyd &>/dev/null; then
    info "Instalando ttyd..."
    brew install ttyd
fi
ok "ttyd ($(ttyd --version 2>&1 | head -1))"

# tmux
if ! command -v tmux &>/dev/null; then
    info "Instalando tmux..."
    brew install tmux
fi
ok "tmux ($(tmux -V))"

# Claude CLI
if ! command -v claude &>/dev/null; then
    warn "Claude CLI não encontrado!"
    echo -e "   Instale com: ${DIM}npm install -g @anthropic-ai/claude-code${NC}"
    echo -e "   Depois rode este instalador novamente."
    exit 1
fi
ok "Claude CLI"

# Python 3
if ! command -v python3 &>/dev/null; then
    warn "Python 3 não encontrado!"
    exit 1
fi
ok "Python 3 ($(python3 --version 2>&1))"

# Tailscale (opcional)
if command -v tailscale &>/dev/null; then
    TS_STATUS=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('Self',{}).get('DNSName','?'))" 2>/dev/null || echo "?")
    ok "Tailscale (${TS_STATUS})"
else
    warn "Tailscale não detectado — acesso será apenas local"
    info "Instale em: https://tailscale.com/download/mac"
fi

# ── 2. Instalar arquivos ──
step "2/5  Instalando Claude Hub..."

mkdir -p "$INSTALL_DIR"

# Detecta diretório fonte
SRC_DIR="."
if [ ! -f "claude-hub.py" ] && [ -f "$(dirname "$0")/claude-hub.py" ]; then
    SRC_DIR="$(dirname "$0")"
fi

if [ ! -f "$SRC_DIR/claude-hub.py" ]; then
    warn "claude-hub.py não encontrado no diretório atual!"
    info "Certifique-se de rodar o instalador do mesmo diretório do claude-hub.py"
    exit 1
fi

# Copia script principal + templates
cp "$SRC_DIR/claude-hub.py" "$INSTALL_DIR/claude-hub.py"
chmod +x "$INSTALL_DIR/claude-hub.py"

mkdir -p "$INSTALL_DIR/templates"
cp "$SRC_DIR/templates/"*.html "$INSTALL_DIR/templates/" 2>/dev/null
ok "Servidor + templates instalados em $INSTALL_DIR"

# ── 3. Criar LaunchAgent ──
step "3/5  Configurando inicialização automática..."

PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

# Para o serviço anterior se existir
if launchctl list "$LABEL" &>/dev/null 2>&1; then
    info "Parando serviço anterior..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

TTYD_PATH=$(which ttyd)
PYTHON_PATH=$(which python3)
CLAUDE_PATH=$(which claude)

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${INSTALL_DIR}/claude-hub.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$(dirname "$CLAUDE_PATH")</string>
        <key>TTYD_BIN</key>
        <string>${TTYD_PATH}</string>
        <key>CLAUDE_BIN</key>
        <string>${CLAUDE_PATH}</string>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>CLAUDE_HUB_PORT</key>
        <string>${HUB_PORT}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${INSTALL_DIR}/hub.log</string>
    <key>StandardErrorPath</key>
    <string>${INSTALL_DIR}/hub-error.log</string>
    <key>WorkingDirectory</key>
    <string>${HOME}</string>
</dict>
</plist>
PLIST

ok "LaunchAgent criado"

# ── 4. Iniciar serviço ──
step "4/5  Iniciando Claude Hub..."

launchctl load "$PLIST_PATH"
sleep 1

# Verifica se está rodando
if lsof -i ":${HUB_PORT}" &>/dev/null; then
    ok "Servidor rodando na porta ${HUB_PORT}"
else
    warn "Servidor pode não ter iniciado. Verifique os logs:"
    echo -e "   ${DIM}cat $INSTALL_DIR/hub-error.log${NC}"
fi

# ── 5. Criar script de controle ──
step "5/5  Criando comandos de controle..."

cat > "$INSTALL_DIR/ctl.sh" << 'CTLEOF'
#!/bin/bash
LABEL="com.claude-hub.server"
INSTALL_DIR="$HOME/.claude-hub"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

case "${1:-status}" in
    start)
        launchctl load "$PLIST" 2>/dev/null
        echo "✅ Claude Hub iniciado"
        ;;
    stop)
        launchctl unload "$PLIST" 2>/dev/null
        # Mata ttyd orphans
        pkill -f "ttyd -p 77" 2>/dev/null
        echo "🛑 Claude Hub parado"
        ;;
    restart)
        $0 stop && sleep 1 && $0 start
        ;;
    status)
        if launchctl list "$LABEL" &>/dev/null 2>&1; then
            echo "🟢 Claude Hub está rodando"
            echo ""
            tmux list-sessions -F "   #{session_name}" 2>/dev/null | grep claude || echo "   Nenhuma sessão ativa"
        else
            echo "🔴 Claude Hub está parado"
        fi
        ;;
    logs)
        tail -f "$INSTALL_DIR/hub.log" "$INSTALL_DIR/hub-error.log"
        ;;
    uninstall)
        echo "Removendo Claude Hub..."
        launchctl unload "$PLIST" 2>/dev/null
        pkill -f "ttyd -p 77" 2>/dev/null
        rm -f "$PLIST"
        rm -rf "$INSTALL_DIR"
        rm -f /usr/local/bin/claude-hub
        echo "✅ Claude Hub removido"
        ;;
    *)
        echo "Uso: claude-hub {start|stop|restart|status|logs|uninstall}"
        ;;
esac
CTLEOF

chmod +x "$INSTALL_DIR/ctl.sh"

# Symlink para uso global
ln -sf "$INSTALL_DIR/ctl.sh" /usr/local/bin/claude-hub 2>/dev/null || \
    sudo ln -sf "$INSTALL_DIR/ctl.sh" /usr/local/bin/claude-hub 2>/dev/null || \
    warn "Não foi possível criar symlink em /usr/local/bin (rode com sudo se quiser)"

ok "Comando 'claude-hub' disponível"

# ── Done ──

# Detectar hostname do Tailscale
TS_HOSTNAME=""
if command -v tailscale &>/dev/null; then
    TS_HOSTNAME=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin).get('Self',{}).get('DNSName','');print(d.rstrip('.'))" 2>/dev/null || echo "")
fi

echo ""
echo -e "${BOLD}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD} ✅ Claude Hub instalado com sucesso!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════${NC}"
echo ""
echo -e " ${BOLD}Acesso local:${NC}"
echo -e "   http://localhost:${HUB_PORT}"
echo ""
if [ -n "$TS_HOSTNAME" ]; then
    echo -e " ${BOLD}Acesso via Tailscale (celular):${NC}"
    echo -e "   ${GREEN}http://${TS_HOSTNAME}:${HUB_PORT}${NC}"
    echo ""
fi
echo -e " ${BOLD}Comandos:${NC}"
echo -e "   ${DIM}claude-hub status${NC}     — ver status"
echo -e "   ${DIM}claude-hub stop${NC}       — parar"
echo -e "   ${DIM}claude-hub start${NC}      — iniciar"
echo -e "   ${DIM}claude-hub restart${NC}    — reiniciar"
echo -e "   ${DIM}claude-hub logs${NC}       — ver logs"
echo -e "   ${DIM}claude-hub uninstall${NC}  — desinstalar"
echo ""
echo -e " ${BOLD}📱 Dica:${NC} No iPhone, abra o link no Safari e"
echo -e "    use ${DIM}Compartilhar → Adicionar à Tela Inicial${NC}"
echo -e "    pra virar um \"app\"!"
echo ""
