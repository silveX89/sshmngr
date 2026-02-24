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
3. `display_ui()` renders header + host table via `rich`
4. `run_prompt()` presents a `prompt_toolkit` fuzzy-autocomplete prompt
5. `find_entry()` resolves the typed string to a `HostEntry`
6. `build_ssh_command()` constructs the `ssh` command list
7. `subprocess.call()` hands off to system SSH

**Config file search order:** CWD first, then `~/.config/sshmngr/`. This allows per-project configs by running `sshmngr` from a directory containing its own `config.ini` / `hosts.csv`.

**SSH banner fix:** System SSH is used with `-J` (ProxyJump) instead of paramiko. This handles SSH banners from target hosts natively. The generated command looks like:
```
ssh -J jumpuser@jumpserver user@target-ip
```

**`hosts.csv` format detection** (in `load_hosts`):
- Header contains `hostname` → full format (`hostname,host,port,user,jumphost,jumpuser,notes[,legacy]`)
- Header contains `name` + `ip address` → XIQ-SE export format; optional columns: `port`, `user`, `jumphost`, `jumpuser`, `notes`, `legacy`; all other columns ignored
- Header contains `host` + `addr` → two-column shorthand
- Any other header → first col = hostname, second col = IP
- No header → raw hostnames, one per line

**`config.ini`** has no `[section]` header — `_preprocess_ini()` injects `[main]` before passing to `configparser`. Keys: `global_jumphost` (yes/no), `jumpserver`, `jumpuser`, `ssh_user`.

**`find_entry()` resolution order:** exact hostname → unique prefix → exact IP/host → literal fallback (passed raw to `ssh`).

**Dependencies:** `rich` (display), `prompt_toolkit` (interactive prompt). Both are optional — the code degrades gracefully if either is missing (`RICH_OK` / `PROMPT_OK` flags). Without `prompt_toolkit`, falls back to plain `input()`.

**Entry point:** `sshmngr.sshmngr:main` as defined in `pyproject.toml`. Version string is `VERSION` at the top of `sshmngr.py`; update both it and `pyproject.toml` when bumping.

**History file:** `~/.config/sshmngr/.history` (prompt_toolkit FileHistory).
