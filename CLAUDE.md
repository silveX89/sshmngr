# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e .          # editable install (picks up changes without reinstall)

# Run
sshmngr                   # interactive TUI
sshmngr <hostname>        # connect directly
sshmngr --list-hosts      # print all known hosts (used by bash completion)

# Bash completion (optional, one-time)
source completions/sshmngr.bash
```

There are no tests or linting configurations in this project.

## Architecture

All logic lives in a single file: `sshmngr/sshmngr.py`.

**Data flow:**
1. `load_config()` reads `config.ini` → `Config` dataclass
2. `load_hosts()` reads `hosts.csv` → list of `HostEntry` dataclasses
3. `display_ui()` renders wizard banner + host table via `rich`
4. `run_prompt()` presents a `prompt_toolkit` fuzzy-autocomplete prompt
5. `find_entry()` resolves the typed string to a `HostEntry`
6. `build_ssh_command()` constructs the `ssh` command list
7. `subprocess.call()` hands off to system SSH

**Config file search order:** CWD first, then `~/.config/sshmngr/`. This allows per-project configs by running `sshmngr` from a directory containing its own `config.ini` / `hosts.csv`.

**`hosts.csv` format detection** (in `load_hosts`):
- Header contains `hostname` → full format (`hostname,host,port,user,jumphost,jumpuser,notes[,legacy]`)
- Header contains `name` + `ip address` → maps `Name`→hostname, `IP Address`→host; optional columns: `port`, `user`, `jumphost`, `jumpuser`, `notes`, `legacy`; all other columns ignored
- Header contains `host` + `addr` → two-column shorthand
- Any other header → first col = hostname, second col = IP
- No header → raw hostnames, one per line

**`config.ini`** has no `[section]` header — `_preprocess_ini()` injects `[main]` before passing to `configparser`. Keys: `global_jumphost` (yes/no), `jumpserver`, `jumpuser`, `ssh_user`.

**Slash-command system** (`CmdFlags` dataclass + `parse_command()`):

| Flag | `CmdFlags` field | SSH effect |
|------|-----------------|------------|
| `/o` | `bypass_jumphost` | Omits `-J` jump spec entirely |
| `/v` | `verbose` | Adds `-v` to ssh |
| `/d` | `dry_run` | Prints command, skips `subprocess.call` |
| `/l` | `legacy` | Adds `-o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa` |

Commands are stackable (e.g. `/l/v hostname`). In `run_prompt()` the WoW-style activation fires on **Space** after typing the prefix — `_CMD_MAP` maps each prefix string to the matching `_mode` key. The `_dynamic_prompt()` callable rebuilds the prompt label whenever a mode is active.

The `legacy` flag can also be set **per-host** via a `legacy=yes` column in `hosts.csv` (full or XIQ-SE format). `main()` merges `entry.legacy` into `flags.legacy` before calling `build_ssh_command()`.

**Scrollable host list** — when `len(entries) > _visible_count(terminal_height)`, `main()` passes only the first visible slice to `display_ui()` (with `total_count` set so a scroll indicator renders). `run_prompt()` then binds `up`/`down` (eager, overriding history nav) to adjust `_offset` and calls `event.app.run_in_terminal(_redraw)`, which clears the screen and re-renders the visible slice. `_UI_OVERHEAD = len(_WIZARD_LINES) + 12` (≈ 23) is the fixed chrome line count; `_visible_count()` returns `max(3, term_height − _UI_OVERHEAD)`. Scroll bindings are only registered when `needs_scroll` is True (both `RICH_OK` and `PROMPT_OK` required).

**`find_entry()` resolution order:** exact hostname → unique prefix → exact IP/host → literal fallback (passed raw to `ssh`).

**Dependencies:** `rich` (display), `prompt_toolkit` (interactive prompt). Both optional — degrades gracefully if missing (`RICH_OK` / `PROMPT_OK` flags). Without `prompt_toolkit`, falls back to plain `input()`.

**Version string** lives in two places — keep them in sync when bumping:
- `VERSION` constant at the top of `sshmngr/sshmngr.py`
- `version` field in `pyproject.toml`

**Entry point:** `sshmngr.sshmngr:main` as defined in `pyproject.toml`.

**History file:** `~/.config/sshmngr/.history` (prompt_toolkit `FileHistory`).
