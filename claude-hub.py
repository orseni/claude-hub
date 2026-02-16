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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_template_cache = {}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_template(name: str) -> str:
    """Carrega template HTML de templates/ com cache em memória."""
    if name not in _template_cache:
        path = os.path.join(SCRIPT_DIR, "templates", name)
        with open(path, "r", encoding="utf-8") as f:
            _template_cache[name] = f.read()
    return _template_cache[name]


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

    if not target.startswith(base):
        target = base

    folders = []
    try:
        for entry in sorted(os.scandir(target), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith(".") and entry.name not in IGNORED_DIRS:
                folders.append(entry.name)
    except PermissionError:
        pass

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
        subprocess.run([TMUX_BIN, "set-option", "-t", session, "mouse", "on"],
                       capture_output=True)

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


# ─── HTML Rendering ──────────────────────────────────────────────────────────

def render_hub(host: str) -> str:
    """Renderiza o dashboard com sessões ativas."""
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

    html = _load_template("hub.html")
    return html.replace("{{COUNT_TEXT}}", count_text).replace("{{SESSION_CARDS}}", session_cards)


def render_terminal(name: str, port: int, host: str) -> str:
    """Renderiza a página wrapper do terminal."""
    terminal_url = f"https://{host}:{port}"
    html = _load_template("terminal.html")
    return html.replace("{{SESSION_NAME}}", name).replace("{{TERMINAL_URL}}", terminal_url)


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class HubHandler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
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

        # API: check if ttyd is ready
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

        # Download certificado SSL
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
        pass


# ─── CLI ──────────────────────────────────────────────────────────────────────

def find_hub_pid() -> int | None:
    try:
        out = subprocess.check_output(
            [LSOF_BIN, "-ti", f":{HUB_PORT}"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if out:
            return int(out.split("\n")[0])
    except (subprocess.CalledProcessError, ValueError):
        pass
    return None


def cmd_stop():
    pid = find_hub_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        print(f"🛑 Claude Hub parado (PID {pid})")
    else:
        print("🔴 Claude Hub não está rodando")
    subprocess.run([PKILL_BIN, "-f", "ttyd -p 77"], capture_output=True)


def cmd_status():
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
║          🤖 Claude Hub v2.3             ║
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
