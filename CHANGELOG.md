# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **Uninstall command** via `claude-hub uninstall`
- Complete open source infrastructure: LICENSE (MIT), CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, ROADMAP.md
- GitHub issue templates (bug report, feature request) and PR template
- `.editorconfig` for consistent formatting

### Changed
- **Complete UI redesign**: modern dark theme with blue-tinted palette, CSS status indicators (replaces emoji), SVG icons, responsive layout
- **All text translated to English** (was Portuguese): UI, code comments, docstrings, error messages, documentation
- **README completely rewritten** in English with marketing intro, multi-OS guides, architecture diagram, API reference
- Binary paths now use `shutil.which()` instead of hardcoded `/opt/homebrew/` paths
- Default `DEV_ROOT` changed from `~/Desenvolvimento` to `~/Projects`
- Install directory configurable via `CLAUDE_HUB_DIR` environment variable
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
