#!/usr/bin/env python3
"""
Claude Hub — Acesse suas sessões do Claude Code pelo celular via Tailscale.
Um mini servidor web que gerencia sessões ttyd + tmux.
"""

import subprocess
import os
import sys
import signal
import time
import json
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, parse_qs, urlparse
from datetime import datetime

# ─── Config ───────────────────────────────────────────────────────────────────
HUB_PORT = int(os.environ.get("CLAUDE_HUB_PORT", 7680))
BASE_PORT = 7700
MAX_PORT = 7799
TTYD_BIN = os.environ.get("TTYD_BIN", "/opt/homebrew/bin/ttyd")
TMUX_BIN = "/opt/homebrew/bin/tmux"
LSOF_BIN = "/usr/sbin/lsof"
PKILL_BIN = "/usr/bin/pkill"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
FONT_SIZE = int(os.environ.get("CLAUDE_FONT_SIZE", 11))
DEV_ROOT = os.environ.get("CLAUDE_DEV_ROOT", os.path.expanduser("~/Desenvolvimento"))


IGNORED_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", ".tox",
                ".mypy_cache", ".pytest_cache", "dist", "build", ".next", ".nuxt"}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def port_for_name(name: str) -> int:
    """Gera porta determinística baseada no nome (7700-7799)."""
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return BASE_PORT + (h % (MAX_PORT - BASE_PORT))


def get_ttyd_ports() -> set[int]:
    """Retorna set de portas onde ttyd está rodando."""
    try:
        out = subprocess.check_output(
            [LSOF_BIN, "-iTCP:7700-7799", "-sTCP:LISTEN", "-P", "-n"],
            text=True, stderr=subprocess.DEVNULL
        )
        ports = set()
        for line in out.strip().split("\n"):
            if "LISTEN" in line:
                for part in line.split():
                    if ":" in part and part.split(":")[-1].isdigit():
                        ports.add(int(part.split(":")[-1]))
        return ports
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()


def port_in_use(port: int) -> bool:
    """Checa se uma porta já está em uso."""
    r = subprocess.run([LSOF_BIN, "-i", f":{port}"], capture_output=True)
    return r.returncode == 0


def get_sessions() -> list[dict]:
    """Lista sessões tmux ativas do Claude."""
    try:
        # Roda tmux e lsof em paralelo pra reduzir latência
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            tmux_future = ex.submit(
                subprocess.check_output,
                [TMUX_BIN, "list-sessions", "-F",
                 "#{session_name}|#{session_activity}|#{session_windows}|#{session_attached}"],
                text=True, stderr=subprocess.DEVNULL
            )
            ports_future = ex.submit(get_ttyd_ports)
            out = tmux_future.result(timeout=3)
            ttyd_ports = ports_future.result(timeout=3)
        sessions = []
        for line in out.strip().split("\n"):
            if not line.startswith("claude-"):
                continue
            parts = line.split("|")
            name = parts[0].removeprefix("claude-")
            try:
                last_activity = datetime.fromtimestamp(int(parts[1]))
                time_str = last_activity.strftime("%H:%M")
            except (ValueError, IndexError):
                time_str = "?"
            attached = parts[3] if len(parts) > 3 else "0"
            port = port_for_name(name)
            sessions.append({
                "name": name,
                "port": port,
                "time": time_str,
                "attached": attached != "0",
                "has_ttyd": port in ttyd_ports,
            })
        return sessions
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def get_folders(rel_path: str = "") -> dict:
    """Lista subpastas de um caminho relativo ao DEV_ROOT."""
    base = os.path.realpath(DEV_ROOT)
    target = os.path.realpath(os.path.join(base, rel_path)) if rel_path else base

    # Segurança: não permite navegar acima de DEV_ROOT
    if not target.startswith(base):
        target = base

    folders = []
    try:
        for entry in sorted(os.scandir(target), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith(".") and entry.name not in IGNORED_DIRS:
                folders.append(entry.name)
    except PermissionError:
        pass

    # Caminho relativo para exibição
    display_path = os.path.relpath(target, base)
    if display_path == ".":
        display_path = ""

    return {
        "folders": folders,
        "current": display_path,
        "absolute": target,
        "can_go_up": target != base,
        "root_name": os.path.basename(base),
    }


def start_session(name: str, directory: str = None, skip_permissions: bool = False) -> int:
    """Inicia uma sessão tmux + ttyd. Retorna a porta."""
    port = port_for_name(name)
    session = f"claude-{name}"

    # Cria sessão tmux se não existe
    r = subprocess.run([TMUX_BIN, "has-session", "-t", session],
                       capture_output=True)
    if r.returncode != 0:
        cmd = [TMUX_BIN, "new-session", "-d", "-s", session]
        if directory and os.path.isdir(directory):
            cmd += ["-c", directory]
        cmd.append(CLAUDE_BIN)
        if skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.5)
        # Habilita mouse para scroll funcionar no browser
        subprocess.run([TMUX_BIN, "set-option", "-t", session, "mouse", "on"],
                       capture_output=True)

    # Inicia ttyd se não está rodando nessa porta
    if not port_in_use(port):
        subprocess.Popen(
            [TTYD_BIN, "-W", "-p", str(port),
             "--ping-interval", "5",
             "-t", f"fontSize={FONT_SIZE}",
             "-I", os.path.expanduser("~/.claude-hub/ttyd-index.html"),
             "-S", "-C", os.path.expanduser("~/.claude-hub/hub.crt"),
             "-K", os.path.expanduser("~/.claude-hub/hub.key"),
             "-t", "theme={\"background\":\"#0f0f1a\",\"foreground\":\"#e8e8f0\",\"cursor\":\"#7c83ff\"}",
             "-t", "titleFixed=Claude Hub",
             "tmux", "attach-session", "-t", session],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.3)

    return port


def stop_session(name: str):
    """Para ttyd e mata a sessão tmux."""
    port = port_for_name(name)
    session = f"claude-{name}"
    subprocess.run([PKILL_BIN, "-f", f"ttyd -p {port}"],
                   capture_output=True)
    subprocess.run([TMUX_BIN, "kill-session", "-t", session],
                   capture_output=True)


# ─── HTML ─────────────────────────────────────────────────────────────────────

def render_hub(host: str) -> str:
    sessions = get_sessions()

    session_cards = ""
    for s in sessions:
        status_dot = "🟢" if s["has_ttyd"] else "🔵"
        attached_badge = '<span class="badge active">conectado</span>' if s["attached"] else ""

        danger_class = " card-danger" if s["name"] == "danguly-skip-perm" else ""
        session_cards += f"""
        <div class="card{danger_class}">
          <a href="/start/{s['name']}" class="card-link">
            <div class="card-left">
              <span class="status-dot">{status_dot}</span>
              <div>
                <div class="card-name">{s['name']}</div>
                <div class="card-meta">porta {s['port']} · {s['time']}</div>
              </div>
            </div>
            <div class="card-right">
              {attached_badge}
              <span class="arrow">›</span>
            </div>
          </a>
          <button class="stop-btn" onclick="event.preventDefault();if(confirm('Encerrar sessão {s['name']}?'))location='/stop/{s['name']}'">✕</button>
        </div>"""

    if not sessions:
        session_cards = """
        <div class="empty">
          <div class="empty-icon">⌨️</div>
          <p>Nenhuma sessão ativa</p>
          <p class="empty-sub">Crie uma abaixo para começar</p>
        </div>"""

    count = len(sessions)
    count_text = f"{count} sessão ativa" if count == 1 else f"{count} sessões ativas"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Claude Hub">
<meta name="theme-color" content="#0c0c0c">
<title>Claude Hub</title>
<link rel="apple-touch-icon" href="/icon.png">
<style>
  :root {{
    --bg: #0c0c0c;
    --surface: #161616;
    --surface-hover: #1e1e1e;
    --border: #2a2a2a;
    --text: #e0ddd5;
    --text-dim: #7a7770;
    --accent: #E8734A;
    --accent-glow: rgba(232, 115, 74, 0.12);
    --danger: #c44;
    --success: #5a9a5a;
    --radius: 10px;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: -apple-system, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100dvh;
    padding: env(safe-area-inset-top) 16px 100px;
    -webkit-font-smoothing: antialiased;
  }}

  /* ── Header ── */
  .header {{
    padding: 40px 0 8px;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }}

  .logo {{
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 26px;
    font-weight: 600;
    background: linear-gradient(135deg, #E8734A, #F4A77A);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
  }}

  .subtitle {{
    color: var(--text-dim);
    font-size: 13px;
    margin-bottom: 24px;
  }}

  .counter {{
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 12px;
    color: var(--text-dim);
    background: var(--surface);
    padding: 4px 10px;
    border-radius: 20px;
    border: 1px solid var(--border);
  }}

  /* ── Cards ── */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
  }}

  .card:active {{
    transform: scale(0.98);
    background: var(--surface-hover);
  }}

  .card.card-danger {{
    background: rgba(140, 30, 30, 0.2);
    border-color: rgba(200, 60, 60, 0.4);
  }}

  .card.card-danger:active {{
    background: rgba(140, 30, 30, 0.3);
  }}

  .card.card-danger .card-name {{
    color: #d07070;
  }}

  .card-link {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px;
    text-decoration: none;
    color: inherit;
    -webkit-tap-highlight-color: transparent;
  }}

  .card-left {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}

  .status-dot {{ font-size: 10px; }}

  .card-name {{
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-weight: 600;
    font-size: 16px;
    color: var(--text);
  }}

  .card-meta {{
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 2px;
  }}

  .card-right {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  .badge {{
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 20px;
    font-weight: 500;
  }}

  .badge.active {{
    background: rgba(90, 154, 90, 0.15);
    color: var(--success);
  }}

  .arrow {{
    color: var(--text-dim);
    font-size: 22px;
    font-weight: 300;
  }}

  .stop-btn {{
    background: none;
    border: none;
    color: var(--text-dim);
    font-size: 14px;
    padding: 16px 16px 16px 8px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: color 0.2s;
  }}

  .stop-btn:hover {{ color: var(--danger); }}

  /* ── Empty State ── */
  .empty {{
    text-align: center;
    padding: 48px 20px;
    color: var(--text-dim);
  }}

  .empty-icon {{ font-size: 40px; margin-bottom: 12px; }}
  .empty p {{ font-size: 16px; }}
  .empty-sub {{ font-size: 13px; margin-top: 4px; opacity: 0.6; }}

  /* ── New Session Form ── */
  .form-section {{
    margin-top: 24px;
    padding-top: 24px;
    border-top: 1px solid var(--border);
  }}

  .form-label {{
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-dim);
    margin-bottom: 10px;
    display: block;
  }}

  .form-row {{
    display: flex;
    gap: 10px;
  }}

  .form-input {{
    flex: 1;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    color: var(--text);
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 15px;
    outline: none;
    transition: border-color 0.2s;
    -webkit-appearance: none;
  }}

  .form-input::placeholder {{ color: var(--text-dim); opacity: 0.5; }}
  .form-input:focus {{ border-color: var(--accent); }}

  .form-btn {{
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: var(--radius);
    padding: 14px 20px;
    font-family: -apple-system, system-ui, sans-serif;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: all 0.2s;
    white-space: nowrap;
  }}

  .form-btn:active {{
    transform: scale(0.96);
    opacity: 0.9;
  }}


  /* ── Quick Actions ── */
  .quick-actions {{
    display: flex;
    gap: 8px;
    margin-top: 12px;
    flex-wrap: wrap;
  }}

  .quick-btn {{
    background: var(--accent-glow);
    border: 1px solid rgba(124, 131, 255, 0.2);
    color: var(--accent);
    border-radius: 10px;
    padding: 10px 14px;
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 13px;
    cursor: pointer;
    text-decoration: none;
    -webkit-tap-highlight-color: transparent;
    transition: all 0.2s;
  }}

  .quick-btn:active {{
    transform: scale(0.96);
    background: rgba(212, 148, 58, 0.25);
  }}

  /* ── Folder Picker Modal ── */
  .modal-overlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    z-index: 1000;
    animation: fadeOverlay 0.25s ease-out;
  }}

  .modal-overlay.active {{ display: flex; align-items: flex-end; justify-content: center; }}

  @keyframes fadeOverlay {{
    from {{ opacity: 0; }}
    to {{ opacity: 1; }}
  }}

  .modal {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 20px 20px 0 0;
    width: 100%;
    max-width: 500px;
    max-height: 85dvh;
    display: flex;
    flex-direction: column;
    animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }}

  @keyframes slideUp {{
    from {{ transform: translateY(100%); }}
    to {{ transform: translateY(0); }}
  }}

  .modal-handle {{
    width: 36px;
    height: 4px;
    background: var(--border);
    border-radius: 4px;
    margin: 10px auto 0;
    flex-shrink: 0;
  }}

  .modal-header {{
    padding: 16px 20px 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }}

  .modal-title {{
    font-family: -apple-system, system-ui, sans-serif;
    font-size: 18px;
    font-weight: 600;
  }}

  .modal-close {{
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text-dim);
    width: 32px;
    height: 32px;
    border-radius: 50%;
    font-size: 16px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    -webkit-tap-highlight-color: transparent;
  }}

  .modal-close:active {{ background: var(--surface-hover); }}

  /* Breadcrumb */
  .breadcrumb {{
    padding: 0 20px 12px;
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
    flex-shrink: 0;
  }}

  .crumb {{
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 12px;
    color: var(--text-dim);
    background: none;
    border: none;
    cursor: pointer;
    padding: 4px 6px;
    border-radius: 6px;
    -webkit-tap-highlight-color: transparent;
  }}

  .crumb:hover {{ background: var(--surface); }}
  .crumb.current {{ color: var(--accent); font-weight: 600; }}
  .crumb-sep {{ color: var(--text-dim); opacity: 0.4; font-size: 11px; }}

  /* Folder list */
  .folder-list {{
    flex: 1;
    overflow-y: auto;
    padding: 0 12px;
    -webkit-overflow-scrolling: touch;
  }}

  .folder-item {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 12px;
    border-radius: 12px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: background 0.15s;
    border: none;
    background: none;
    color: var(--text);
    width: 100%;
    text-align: left;
    font-family: -apple-system, system-ui, sans-serif;
    font-size: 15px;
  }}

  .folder-item:active {{ background: var(--surface-hover); }}

  .folder-icon {{
    width: 40px;
    height: 40px;
    background: var(--accent-glow);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
  }}

  .folder-name {{
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}

  .folder-chevron {{
    margin-left: auto;
    color: var(--text-dim);
    font-size: 18px;
    opacity: 0.5;
    flex-shrink: 0;
  }}

  .folder-empty {{
    text-align: center;
    padding: 40px 20px;
    color: var(--text-dim);
    font-size: 14px;
  }}

  .folder-loading {{
    text-align: center;
    padding: 40px 20px;
    color: var(--text-dim);
    font-size: 14px;
  }}

  /* Select button */
  .modal-footer {{
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
    flex-shrink: 0;
    border-top: 1px solid var(--border);
  }}

  .select-btn {{
    width: 100%;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: var(--radius);
    padding: 16px;
    font-family: -apple-system, system-ui, sans-serif;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: all 0.2s;
  }}

  .select-btn:active {{
    transform: scale(0.98);
    opacity: 0.9;
  }}

  .select-path {{
    display: block;
    font-size: 11px;
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-weight: 400;
    opacity: 0.7;
    margin-top: 4px;
  }}

  /* ── Footer ── */
  .footer {{
    margin-top: 32px;
    text-align: center;
    font-size: 12px;
    color: var(--text-dim);
    opacity: 0.5;
  }}

  /* ── Animations ── */
  @keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  .card, .form-section {{ animation: fadeIn 0.3s ease-out backwards; }}
  .card:nth-child(1) {{ animation-delay: 0.05s; }}
  .card:nth-child(2) {{ animation-delay: 0.1s; }}
  .card:nth-child(3) {{ animation-delay: 0.15s; }}
  .card:nth-child(4) {{ animation-delay: 0.2s; }}
  .form-section {{ animation-delay: 0.25s; }}
</style>
</head>
<body>
  <div class="header">
    <span class="logo">&gt;_ claude hub</span>
    <span class="counter">{count_text}</span>
  </div>
  <p class="subtitle">Sessões do Claude Code</p>

  {session_cards}

  <div class="form-section">
    <label class="form-label">Nova Sessão</label>
    <div class="form-row">
      <input class="form-input" id="session-name" placeholder="nome da sessão" autocapitalize="none" autocorrect="off" spellcheck="false">
      <button class="form-btn" onclick="openFolderPicker()">Criar</button>
    </div>
  </div>

  <div class="footer">
    Claude Hub v2.2 · ttyd + tmux
  </div>

  <!-- Folder Picker Modal -->
  <div class="modal-overlay" id="folder-modal">
    <div class="modal">
      <div class="modal-handle"></div>
      <div class="modal-header">
        <span class="modal-title">Escolher pasta</span>
        <button class="modal-close" onclick="closeFolderPicker()">✕</button>
      </div>
      <div class="breadcrumb" id="breadcrumb"></div>
      <div class="folder-list" id="folder-list">
        <div class="folder-loading">Carregando...</div>
      </div>
      <div class="modal-footer">
        <button class="select-btn" id="select-btn" onclick="confirmSelection()">
          Abrir sessão aqui
          <span class="select-path" id="select-path"></span>
        </button>
      </div>
    </div>
  </div>

  <!-- Skip Permissions Popup -->
  <div class="modal-overlay" id="skip-modal">
    <div class="modal" style="max-height:auto;">
      <div class="modal-handle"></div>
      <div class="modal-header">
        <span class="modal-title">Modo de permissões</span>
        <button class="modal-close" onclick="closeSkipModal()">✕</button>
      </div>
      <div style="padding:16px 20px;">
        <div style="background:rgba(204,68,68,0.08);border:1px solid rgba(204,68,68,0.2);border-radius:10px;padding:14px 16px;margin-bottom:16px;">
          <div style="font-size:14px;font-weight:600;color:var(--danger);margin-bottom:6px;">--dangerously-skip-permissions</div>
          <div style="font-size:13px;color:var(--text-dim);line-height:1.4;">
            O Claude poderá executar comandos, editar e deletar arquivos <strong style="color:var(--danger);">sem pedir confirmação</strong>. Use apenas em projetos que você confia.
          </div>
        </div>
        <button class="select-btn" style="background:var(--danger);margin-bottom:10px;" onclick="launchSession(true)">
          Sim, pular permissões
        </button>
        <button class="select-btn" style="background:var(--accent);" onclick="launchSession(false)">
          Não, modo normal
        </button>
      </div>
    </div>
  </div>

<script>
  let currentPath = '';
  let currentAbsolute = '';
  let sessionName = '';

  function openFolderPicker(name) {{
    const input = document.getElementById('session-name');
    sessionName = name || input.value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-');
    if (!sessionName) {{
      input.focus();
      input.style.borderColor = 'var(--danger)';
      setTimeout(() => input.style.borderColor = '', 1500);
      return;
    }}
    document.getElementById('folder-modal').classList.add('active');
    currentPath = '';
    loadFolders('');
  }}

  function closeFolderPicker() {{
    document.getElementById('folder-modal').classList.remove('active');
  }}

  // Fecha ao clicar fora do modal
  document.getElementById('folder-modal').addEventListener('click', function(e) {{
    if (e.target === this) closeFolderPicker();
  }});

  async function loadFolders(path) {{
    const list = document.getElementById('folder-list');
    list.innerHTML = '<div class="folder-loading">Carregando...</div>';

    try {{
      const res = await fetch('/api/folders?path=' + encodeURIComponent(path));
      const data = await res.json();
      currentPath = data.current;
      currentAbsolute = data.absolute;

      // Breadcrumb
      renderBreadcrumb(data);

      // Select button path
      const pathDisplay = data.current ? data.root_name + '/' + data.current : data.root_name;
      document.getElementById('select-path').textContent = '~/' + pathDisplay;

      // Folder list
      if (data.folders.length === 0) {{
        list.innerHTML = '<div class="folder-empty">Nenhuma subpasta aqui</div>';
        return;
      }}

      list.innerHTML = '';
      data.folders.forEach(name => {{
        const item = document.createElement('button');
        item.className = 'folder-item';
        item.innerHTML = `
          <span class="folder-icon">📁</span>
          <span class="folder-name">${{name}}</span>
          <span class="folder-chevron">›</span>
        `;
        item.onclick = () => {{
          const newPath = data.current ? data.current + '/' + name : name;
          loadFolders(newPath);
        }};
        list.appendChild(item);
      }});

      // Scroll to top
      list.scrollTop = 0;
    }} catch (err) {{
      list.innerHTML = '<div class="folder-empty">Erro ao carregar pastas</div>';
    }}
  }}

  function renderBreadcrumb(data) {{
    const bc = document.getElementById('breadcrumb');
    bc.innerHTML = '';

    // Root
    const rootBtn = document.createElement('button');
    rootBtn.className = 'crumb' + (data.current === '' ? ' current' : '');
    rootBtn.textContent = data.root_name;
    rootBtn.onclick = () => loadFolders('');
    bc.appendChild(rootBtn);

    if (data.current) {{
      const parts = data.current.split('/');
      let accumulated = '';
      parts.forEach((part, i) => {{
        const sep = document.createElement('span');
        sep.className = 'crumb-sep';
        sep.textContent = '›';
        bc.appendChild(sep);

        accumulated += (accumulated ? '/' : '') + part;
        const btn = document.createElement('button');
        btn.className = 'crumb' + (i === parts.length - 1 ? ' current' : '');
        btn.textContent = part;
        const pathForBtn = accumulated;
        btn.onclick = () => loadFolders(pathForBtn);
        bc.appendChild(btn);
      }});
    }}
  }}

  function confirmSelection() {{
    // Fecha o folder picker e abre o popup de permissões
    document.getElementById('folder-modal').classList.remove('active');
    document.getElementById('skip-modal').classList.add('active');
  }}

  function closeSkipModal() {{
    document.getElementById('skip-modal').classList.remove('active');
  }}

  // Fecha ao clicar fora
  document.getElementById('skip-modal').addEventListener('click', function(e) {{
    if (e.target === this) closeSkipModal();
  }});

  function launchSession(skip) {{
    const dir = encodeURIComponent(currentAbsolute);
    const name = encodeURIComponent(sessionName);
    let url = '/start/' + name + '?dir=' + dir;
    if (skip) url += '&skip_permissions=1';
    window.location.href = url;
  }}
</script>
</body>
</html>"""


def render_terminal(name: str, port: int, host: str) -> str:
    """Renderiza a página wrapper do terminal com teclas virtuais."""
    terminal_url = f"https://{host}:{port}"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0c0c0c">
<title>{name} — Claude Hub</title>
<style>
  :root {{
    --bg: #0c0c0c;
    --surface: #161616;
    --surface-hover: #1e1e1e;
    --border: #2a2a2a;
    --text: #e0ddd5;
    --text-dim: #7a7770;
    --accent: #E8734A;
    --danger: #c44;
    --success: #5a9a5a;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  html, body {{
    height: 100%;
    overflow: hidden;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}

  .container {{
    display: flex;
    flex-direction: column;
    height: 100dvh;
    padding-top: env(safe-area-inset-top);
  }}

  /* ── Top bar ── */
  .top-bar {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 10px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    gap: 6px;
  }}

  .top-left {{
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }}

  .back-btn {{
    background: none;
    border: none;
    color: var(--accent);
    font-size: 24px;
    padding: 4px 8px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    flex-shrink: 0;
  }}

  .session-name {{
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}

  .zoom-controls {{
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }}

  .zoom-btn {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    width: 30px;
    height: 30px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    -webkit-tap-highlight-color: transparent;
  }}

  .zoom-btn:active {{
    background: var(--surface-hover);
  }}

  .zoom-level {{
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 10px;
    color: var(--text-dim);
    min-width: 32px;
    text-align: center;
  }}

  /* ── Terminal iframe ── */
  .terminal-wrap {{
    flex: 1;
    overflow: hidden;
    position: relative;
    background: #0c0c0c;
  }}

  .terminal-wrap iframe {{
    display: block;
    border: none;
    background: #0c0c0c;
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }}

  .loading-overlay {{
    position: absolute;
    inset: 0;
    background: #0c0c0c;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    z-index: 10;
    transition: opacity 0.3s;
  }}

  .loading-overlay.hidden {{
    opacity: 0;
    pointer-events: none;
  }}

  .spinner {{
    width: 36px;
    height: 36px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }}

  @keyframes spin {{
    to {{ transform: rotate(360deg); }}
  }}

  .loading-text {{
    color: var(--text-dim);
    font-size: 13px;
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
  }}

  .direct-link {{
    margin-top: 12px;
    padding: 12px 24px;
    background: var(--accent);
    color: #fff;
    border-radius: 10px;
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }}

  .direct-link:active {{
    opacity: 0.8;
    transform: scale(0.96);
  }}

  /* ── Virtual keyboard ── */
  .vk-bar {{
    display: flex;
    gap: 5px;
    padding: 7px 8px calc(7px + env(safe-area-inset-bottom));
    background: var(--surface);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }}

  .vk-bar::-webkit-scrollbar {{ display: none; }}

  .vk-btn {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 9px 11px;
    border-radius: 8px;
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    -webkit-tap-highlight-color: transparent;
    transition: all 0.1s;
    flex-shrink: 0;
  }}

  .vk-btn:active {{
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
    transform: scale(0.93);
  }}

  .vk-btn.danger {{
    color: var(--danger);
    border-color: rgba(204, 68, 68, 0.3);
  }}

  .vk-btn.danger:active {{
    background: var(--danger);
    border-color: var(--danger);
    color: #fff;
  }}

  .vk-btn.special {{
    color: var(--success);
    border-color: rgba(90, 154, 90, 0.3);
  }}

  .vk-btn.special:active {{
    background: var(--success);
    border-color: var(--success);
    color: #fff;
  }}

  .vk-sep {{
    width: 1px;
    background: var(--border);
    flex-shrink: 0;
    margin: 4px 2px;
  }}

  /* ── Toast feedback ── */
  .toast {{
    position: fixed;
    top: 60px;
    left: 50%;
    transform: translateX(-50%) translateY(-20px);
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 16px;
    border-radius: 10px;
    font-family: 'SF Mono', 'Menlo', 'Courier New', monospace;
    font-size: 12px;
    opacity: 0;
    transition: all 0.2s;
    pointer-events: none;
    z-index: 100;
  }}

  .toast.show {{
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }}
</style>
</head>
<body>
  <div class="container">
    <div class="top-bar">
      <div class="top-left">
        <button class="back-btn" onclick="location.href='/'">&#8249;</button>
        <span class="session-name">{name}</span>
      </div>
    </div>

    <div class="terminal-wrap" id="terminal-wrap">
      <div class="loading-overlay" id="loading">
        <div class="spinner"></div>
        <div class="loading-text">Conectando ao terminal...</div>
        <a class="direct-link" id="direct-link" style="display:none">Abrir terminal direto</a>
      </div>
      <iframe id="terminal" allow="clipboard-read; clipboard-write"></iframe>
    </div>

    <div class="vk-bar" id="vk-bar">
      <button class="vk-btn" onclick="sk('Escape')">Esc</button>
      <button class="vk-btn special" onclick="scrollTmux('up')">PgUp</button>
      <button class="vk-btn special" onclick="scrollTmux('down')">PgDn</button>
      <button class="vk-btn" onclick="sk('BTab')">&#8679;Tab</button>
      <div class="vk-sep"></div>
      <button class="vk-btn" onclick="sk('Up')">&#9650;</button>
      <button class="vk-btn" onclick="sk('Down')">&#9660;</button>
      <button class="vk-btn" onclick="sk('Left')">&#9664;</button>
      <button class="vk-btn" onclick="sk('Right')">&#9654;</button>
      <div class="vk-sep"></div>
      <button class="vk-btn" onclick="sendText('/')">/</button>
      <button class="vk-btn" onclick="sk('Tab')">Tab</button>
      <button class="vk-btn danger" onclick="sk('C-c')">^C</button>
      <button class="vk-btn" onclick="sk('C-z')">^Z</button>
      <button class="vk-btn" onclick="sk('C-d')">^D</button>
      <button class="vk-btn" onclick="sk('C-l')">^L</button>
      <button class="vk-btn" onclick="sk('C-a')">^A</button>
      <button class="vk-btn" onclick="sk('C-e')">^E</button>
      <button class="vk-btn" onclick="sk('C-r')">^R</button>
      <button class="vk-btn" onclick="sk('C-u')">^U</button>
      <button class="vk-btn" onclick="sk('C-k')">^K</button>
      <button class="vk-btn" onclick="sk('C-w')">^W</button>
      <div class="vk-sep"></div>
      <button class="vk-btn special" onclick="pasteClipboard()">Colar</button>
    </div>
  </div>

  <div class="toast" id="toast"></div>

<script>
  const SESSION = "{name}";
  const TERMINAL_URL = "{terminal_url}";

  const iframe = document.getElementById('terminal');
  const loading = document.getElementById('loading');
  const loadingText = loading.querySelector('.loading-text');
  const directLink = document.getElementById('direct-link');

  directLink.href = TERMINAL_URL;

  // iOS: redireciona direto pro ttyd (Safari bloqueia WS cross-origin em iframe)
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

  async function connectTerminal() {{
    loading.classList.remove('hidden');
    loadingText.textContent = 'Conectando ao terminal...';
    let attempts = 0;
    while (true) {{
      try {{
        const r = await fetch('/api/ttyd-ready/' + encodeURIComponent(SESSION));
        const data = await r.json();
        if (data.ready) break;
      }} catch(e) {{}}
      attempts++;
      if (attempts > 3) loadingText.textContent = 'Aguardando terminal...';
      await new Promise(ok => setTimeout(ok, 300));
    }}
    if (isIOS) {{
      // Safari iOS bloqueia WebSocket cross-origin em iframes
      // Salva no localStorage como fallback (caso hash se perca)
      try {{
        localStorage.setItem('claudeHub_origin', location.origin);
        localStorage.setItem('claudeHub_session', SESSION);
      }} catch(e) {{}}
      // Redireciona direto pro ttyd (same-origin = WS funciona)
      window.location.replace(TERMINAL_URL + '#hub=' + encodeURIComponent(location.origin) + '&session=' + encodeURIComponent(SESSION));
      return;
    }}
    iframe.src = TERMINAL_URL;
    iframe.onload = () => loading.classList.add('hidden');
    setTimeout(() => loading.classList.add('hidden'), 3000);
  }}

  connectTerminal();

  // Safari mata WebSocket quando a aba vai pro background — reconecta ao voltar
  document.addEventListener('visibilitychange', () => {{
    if (document.visibilityState === 'visible' && iframe.src) {{
      // Recarrega o iframe para reconectar o WebSocket
      const src = iframe.src;
      iframe.src = '';
      loading.classList.remove('hidden');
      loadingText.textContent = 'Reconectando...';
      setTimeout(() => {{
        iframe.src = src;
        iframe.onload = () => loading.classList.add('hidden');
        setTimeout(() => loading.classList.add('hidden'), 2000);
      }}, 100);
    }}
  }});

  function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 800);
  }}

  async function sk(key) {{
    try {{
      const res = await fetch('/api/send-keys/' + encodeURIComponent(SESSION), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ key: key }})
      }});
      if (!res.ok) showToast('Erro ao enviar tecla');
    }} catch(e) {{
      showToast('Falha na conexão');
    }}
  }}

  async function sendText(text) {{
    try {{
      const res = await fetch('/api/send-text/' + encodeURIComponent(SESSION), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ text: text }})
      }});
      if (!res.ok) showToast('Erro ao enviar texto');
    }} catch(e) {{
      showToast('Falha na conexão');
    }}
  }}

  async function pasteClipboard() {{
    try {{
      const text = await navigator.clipboard.readText();
      if (!text) {{ showToast('Clipboard vazio'); return; }}
      const res = await fetch('/api/send-text/' + encodeURIComponent(SESSION), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ text: text }})
      }});
      if (res.ok) {{
        showToast('Colado!');
      }} else {{
        showToast('Erro ao colar');
      }}
    }} catch(e) {{
      showToast('Sem acesso ao clipboard');
    }}
  }}

  async function scrollTmux(dir) {{
    try {{
      await fetch('/api/scroll/' + encodeURIComponent(SESSION), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ direction: dir }})
      }});
    }} catch(e) {{
      showToast('Erro no scroll');
    }}
  }}
</script>
</body>
</html>"""


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class HubHandler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        """Adiciona headers CORS para permitir chamadas do ttyd (porta diferente)."""
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)

        # Start session
        if path.startswith("/start/"):
            name = path.split("/start/")[1].strip("/")
            if not name:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            directory = qs.get("dir", [None])[0]
            skip_permissions = qs.get("skip_permissions", ["0"])[0] == "1"
            start_session(name, directory, skip_permissions)
            self.send_response(302)
            self.send_header("Location", f"/terminal/{name}")
            self.end_headers()
            return

        # Terminal wrapper
        if path.startswith("/terminal/"):
            name = path.split("/terminal/")[1].strip("/")
            if not name:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            port = port_for_name(name)
            host = self.headers.get("Host", "localhost").split(":")[0]
            html = render_terminal(name, port, host)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(html.encode())
            return

        # Stop session
        if path.startswith("/stop/"):
            name = path.split("/stop/")[1].strip("/")
            stop_session(name)
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        # API: list sessions (JSON)
        if path == "/api/sessions":
            sessions = get_sessions()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(sessions).encode())
            return

        # API: check if ttyd is ready (same-origin, Safari-friendly)
        if path.startswith("/api/ttyd-ready/"):
            name = path.split("/api/ttyd-ready/")[1].strip("/")
            port = port_for_name(name)
            ready = port_in_use(port)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"ready": ready, "port": port}).encode())
            return

        # Download certificado SSL (pra instalar no iOS)
        if path == "/cert":
            cert_path = os.path.expanduser("~/.claude-hub/hub.crt")
            if os.path.exists(cert_path):
                with open(cert_path, "rb") as f:
                    cert_data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-x509-ca-cert")
                self.send_header("Content-Disposition", "attachment; filename=claude-hub.crt")
                self.end_headers()
                self.wfile.write(cert_data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        # API: list folders
        if path == "/api/folders":
            rel_path = qs.get("path", [""])[0]
            data = get_folders(rel_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            return

        # Icon
        if path == "/icon.png":
            icon_path = os.path.expanduser("~/.claude-hub/icon_chub.png")
            if os.path.exists(icon_path):
                with open(icon_path, "rb") as f:
                    icon_data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(icon_data)
            else:
                self.send_response(404)
                self.end_headers()
            return

        # Hub page
        host = self.headers.get("Host", f"localhost:{HUB_PORT}")
        html = render_hub(host)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode())

    def _send_json(self, data, status=200):
        """Envia resposta JSON com CORS."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        # API: send special key via tmux
        if path.startswith("/api/send-keys/"):
            name = path.split("/api/send-keys/")[1].strip("/")
            session = f"claude-{name}"
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            key = data.get("key", "")

            allowed_keys = {
                "Escape", "Tab", "BTab", "Enter", "Space",
                "Up", "Down", "Left", "Right",
                "C-c", "C-v", "C-z", "C-d", "C-l", "C-a", "C-e",
                "C-r", "C-w", "C-u", "C-k", "C-b", "C-f", "C-n", "C-p",
            }

            if key not in allowed_keys:
                self._send_json({"error": "key not allowed"}, 400)
                return

            subprocess.run(
                [TMUX_BIN, "send-keys", "-t", session, key],
                capture_output=True
            )
            self._send_json({"ok": True})
            return

        # API: send text (paste) via tmux
        if path.startswith("/api/send-text/"):
            name = path.split("/api/send-text/")[1].strip("/")
            session = f"claude-{name}"
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            text = data.get("text", "")

            if not text or len(text) > 10000:
                self._send_json({"error": "invalid text"}, 400)
                return

            # Usa tmux load-buffer + paste-buffer para colar texto
            proc = subprocess.run(
                [TMUX_BIN, "load-buffer", "-"],
                input=text, capture_output=True, text=True
            )
            if proc.returncode == 0:
                subprocess.run(
                    [TMUX_BIN, "paste-buffer", "-t", session],
                    capture_output=True
                )

            self._send_json({"ok": True})
            return

        # API: scroll via tmux copy-mode
        if path.startswith("/api/scroll/"):
            name = path.split("/api/scroll/")[1].strip("/")
            session = f"claude-{name}"
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            direction = data.get("direction", "")

            if direction not in ("up", "down"):
                self._send_json({"error": "invalid direction"}, 400)
                return

            # Entra em copy-mode e envia Page Up ou Page Down
            subprocess.run(
                [TMUX_BIN, "copy-mode", "-t", session],
                capture_output=True
            )
            key = "PageUp" if direction == "up" else "PageDown"
            subprocess.run(
                [TMUX_BIN, "send-keys", "-t", session, key],
                capture_output=True
            )

            self._send_json({"ok": True})
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Log silencioso
        pass


# ─── CLI ──────────────────────────────────────────────────────────────────────

def find_hub_pid() -> int | None:
    """Encontra o PID do processo Claude Hub rodando na porta."""
    try:
        out = subprocess.check_output(
            [LSOF_BIN, "-ti", f":{HUB_PORT}"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if out:
            # Pode retornar múltiplos PIDs, pega o primeiro
            return int(out.split("\n")[0])
    except (subprocess.CalledProcessError, ValueError):
        pass
    return None


def cmd_stop():
    """Para o servidor e mata ttyd orphans."""
    pid = find_hub_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        print(f"🛑 Claude Hub parado (PID {pid})")
    else:
        print("🔴 Claude Hub não está rodando")
    # Mata ttyd orphans
    subprocess.run([PKILL_BIN, "-f", "ttyd -p 77"], capture_output=True)


def cmd_status():
    """Mostra status do servidor e sessões."""
    pid = find_hub_pid()
    if pid:
        print(f"🟢 Claude Hub rodando (PID {pid}, porta {HUB_PORT})")
        sessions = get_sessions()
        if sessions:
            for s in sessions:
                dot = "🟢" if s["has_ttyd"] else "🔵"
                print(f"   {dot} {s['name']} (porta {s['port']}, {s['time']})")
        else:
            print("   Nenhuma sessão ativa")
    else:
        print("🔴 Claude Hub está parado")


def cmd_start():
    """Inicia o servidor."""
    # Limpa ttyd orphans ao sair
    def cleanup(sig, frame):
        print("\n🛑 Parando Claude Hub...")
        sessions = get_sessions()
        for s in sessions:
            port = s["port"]
            subprocess.run([PKILL_BIN, "-f", f"ttyd -p {port}"], capture_output=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print(f"""
╔══════════════════════════════════════════╗
║          🤖 Claude Hub v2.2             ║
╠══════════════════════════════════════════╣
║                                          ║
║  Local:     http://localhost:{HUB_PORT}        ║
║  Sessões usam portas {BASE_PORT}-{MAX_PORT}          ║
║  Ctrl+C para parar                       ║
║                                          ║
╚══════════════════════════════════════════╝
""")

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("0.0.0.0", HUB_PORT), HubHandler)

    # SSL — Safari iOS precisa de HTTPS pra WebSocket funcionar de forma confiável
    cert_file = os.path.expanduser("~/.claude-hub/hub.crt")
    key_file = os.path.expanduser("~/.claude-hub/hub.key")
    if os.path.exists(cert_file) and os.path.exists(key_file):
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_file, key_file)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:!aNULL:!MD5')
        ctx.options |= ssl.OP_NO_COMPRESSION | ssl.OP_CIPHER_SERVER_PREFERENCE
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print("🔒 HTTPS ativado")

    server.serve_forever()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"

    if cmd == "stop":
        cmd_stop()
    elif cmd == "restart":
        cmd_stop()
        time.sleep(1)
        cmd_start()
    elif cmd == "status":
        cmd_status()
    elif cmd == "start":
        cmd_start()
    elif cmd == "logs":
        install_dir = os.path.expanduser("~/.claude-hub")
        os.execvp("tail", ["tail", "-f",
                           f"{install_dir}/hub.log",
                           f"{install_dir}/hub-error.log"])
    else:
        print("Uso: claude-hub.py {start|stop|restart|status|logs}")
        sys.exit(1)


if __name__ == "__main__":
    main()
