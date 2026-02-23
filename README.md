# SSHMngr

A tiny SSH connection manager with a rich terminal UI, fuzzy autocomplete, and optional jump host support — driven by a simple CSV inventory.

**v0.7.0** — replaces the old paramiko-based TUI with system `ssh` + [`rich`](https://github.com/Textualize/rich) + [`prompt_toolkit`](https://github.com/prompt-toolkit/python-prompt-toolkit).

---

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .          # editable install — picks up changes without reinstall
```

This exposes the `sshmngr` command on your PATH (within the venv).

**Dependencies** (installed automatically by pip):
- `rich >= 13.0` — terminal table and header rendering
- `prompt_toolkit >= 3.0.43` — fuzzy autocomplete and input history

Both are optional — the tool degrades to a plain `input()` prompt if either is missing.

---

## Usage

```bash
sshmngr                   # interactive TUI — pick a host with fuzzy autocomplete
sshmngr <hostname>        # connect directly, skipping the prompt
sshmngr --list-hosts      # print all known hostnames (used by bash completion)
```

The TUI shows a table of all hosts and prompts for a hostname. Tab-complete or type a prefix to filter. Press **Enter** to connect, **Ctrl+C** to quit.

### Bash completion (optional, one-time)

```bash
source completions/sshmngr.bash
```

Add that line to your `~/.bashrc` for persistent completion.

---

## Configuration files

Files are searched in this order: **current working directory first**, then `~/.config/sshmngr/`. This lets you keep per-project inventories by running `sshmngr` from a project directory containing its own `config.ini` / `hosts.csv`.

| File | Purpose |
|------|---------|
| `config.ini` | Global settings (jump host, default user) |
| `hosts.csv` | Host inventory |

### `config.ini` format

No `[section]` header needed — one is injected automatically.

```ini
# Use the default jumphost for all connections
global_jumphost = yes

# Jump server (DNS name or IP)
jumpserver = 10.0.0.5

# User for the jump server
jumpuser = jumpadmin

# Default SSH user for target hosts
ssh_user = ubuntu
```

| Key | Values | Description |
|-----|--------|-------------|
| `global_jumphost` | `yes` / `no` | When `yes`, all hosts route through `jumpserver` unless overridden per-host |
| `jumpserver` | hostname or IP | Default jump server |
| `jumpuser` | string | User on the jump server |
| `ssh_user` | string | Default user on target hosts |

### `hosts.csv` format

The loader auto-detects the format from the header row:

**Full format** (header contains `hostname`):
```csv
hostname,host,port,user,jumphost,jumpuser,notes
coruscant,192.0.2.10,22,,,
bespin,198.51.100.20,22,root,,
firewall,fw.example.net,2222,admin,jump.company.net,jumper,"mgmt via non-std port"
```

**Shorthand** (header contains `host` + `addr`):
```csv
host,addr
coruscant,192.0.2.10
bespin,198.51.100.20
```

**No header** — one hostname per line:
```
coruscant
bespin
```

**Per-host override rules:**
- `user` overrides the global `ssh_user`.
- `jumphost` / `jumpuser` override the global `jumpserver` / `jumpuser`.
- If `global_jumphost = yes`, the default `jumpserver` is used for every host unless the row sets its own `jumphost`.
- If `global_jumphost = no`, a jump host is only used for rows that explicitly set `jumphost`.

---

## How SSH connections are made

sshmngr delegates entirely to system `ssh`, using `-J` (ProxyJump) for jump hosts:

```
ssh -J jumpadmin@jumpserver ubuntu@192.0.2.10
```

This handles SSH banners and host key checks natively, without any Python SSH library.

**Host resolution order** (when you type a name at the prompt):
1. Exact `hostname` match
2. Unique prefix match
3. Exact IP / `host` field match
4. Literal fallback — passed directly to `ssh` as-is

---

## Repository hygiene

A preconfigured `.gitignore` keeps build artifacts, virtual environments, caches, and OS/editor files out of your repo. By default it **does not** ignore `config.ini` and `hosts.csv` so you can version example files; uncomment those lines in `.gitignore` if you prefer to keep operational configs out of Git.

## License
MIT
