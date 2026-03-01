# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2026-03-01

### Added
- **Capture running sessions**: detect Claude Code CLI processes already running on the host and capture them into the hub with full conversation history
- **Process discovery**: scan for Claude CLI processes outside hub-managed tmux sessions, resolve their working directory and latest session ID
- **`GET /capture` endpoint**: fork a running conversation into a new tmux + ttyd session using `--resume --fork-session`
- **`GET /api/capturable` endpoint**: JSON list of discoverable CLI sessions
- **Dashboard "Running Sessions" section**: shows capturable processes with project name, PID, and working directory
- **Automatic HTTPS setup**: installer now requests Tailscale certificates during installation

### Changed
- Refactored ttyd startup into reusable `_start_ttyd()` helper
- Installer step count updated (5 → 6) to reflect new HTTPS certificate step
- Added `CLAUDE_REMOTE_HUB_DIR` to LaunchAgent and systemd service environments
- Added `/usr/sbin` to service PATH for `lsof` availability on macOS
- Smaller logo font size for better mobile fit
- README updated: new endpoints in API Reference, version badge, feature description, improved HTTPS docs, line count (~600 → ~1000)

## [3.0.1] - 2025-06-16

### Fixed
- Python < 3.10 compatibility: replaced `str | None` union syntax with `Optional[str]`
- Folder picker fallback when `DEV_ROOT` directory doesn't exist

## [3.0.0] - 2025-06-15

### Added
- **Cross-platform support**: Linux (Ubuntu/Debian, Fedora, Arch) and Windows (WSL2) in addition to macOS
- **Cross-platform installer** (`install.sh`): auto-detects OS and package manager, generates OS-appropriate service files
- **systemd user service** for Linux autostart
- **Android browser support**: generalized mobile detection (was iOS-only)
- **Dependency checker** at startup with per-platform install hints
- **`ss` command fallback** for port detection on Linux (when `lsof` unavailable)
- **Socket-based fallback** for universal port-in-use detection
- **`--uninstall` flag** for `install.sh`
- **Uninstall command** via `claude-remote-hub uninstall`
- Complete open source infrastructure: LICENSE (MIT), CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, ROADMAP.md
- GitHub issue templates (bug report, feature request) and PR template
- `.editorconfig` for consistent formatting

### Changed
- **Complete UI redesign**: modern dark theme with blue-tinted palette, CSS status indicators (replaces emoji), SVG icons, responsive layout
- **All text translated to English** (was Portuguese): UI, code comments, docstrings, error messages, documentation
- **README completely rewritten** in English with marketing intro, multi-OS guides, architecture diagram, API reference
- Binary paths now use `shutil.which()` instead of hardcoded `/opt/homebrew/` paths
- Default `DEV_ROOT` changed from `~/Desenvolvimento` to `~/Projects`
- Install directory configurable via `CLAUDE_REMOTE_HUB_DIR` environment variable
- Type hints added to all public functions
- Virtual keyboard label "Colar" renamed to "Paste"
- Dashboard uses safe DOM methods instead of innerHTML

### Removed
- Hardcoded macOS-only paths
- Portuguese language strings
- Emoji-based status indicators (replaced with CSS)

## [2.3.0] - 2025-06-14

### Changed
- Separated HTML into template files (`templates/hub.html`, `templates/terminal.html`)
- Virtual keyboard reorganized into 2-row layout
- Templates loaded via `_load_template()` with in-memory cache

## [2.2.0] - 2025-06-13

### Added
- Initial public release
- HTTP dashboard for managing Claude Code sessions
- ttyd-based web terminal with custom interface
- tmux session management (create, stop, list)
- Virtual keyboard for mobile (special keys, Ctrl combos)
- HTTPS support via Tailscale certificates
- Folder picker for project directory selection
- Paste support via clipboard API
- macOS LaunchAgent for autostart
