# SSHMngr

A lightweight SSH connection manager with optional jump host (bastion) support and CSV-driven inventory.

SSHMngr eliminates the need to remember complex SSH commands and jump host procedures. Define your hosts once in a simple CSV file, configure global defaults, and connect with a single command — either by name or through an interactive terminal UI with real-time search.

---

## Features

- **CSV-based host inventory** — manage all your hosts in a single `hosts.csv` file
- **Jump host / bastion support** — connect through intermediate servers with global or per-host configuration
- **Interactive TUI selection** — full-screen curses interface with real-time search and keyboard navigation
- **Flexible authentication** — automatic key/agent-based auth with password fallback
- **Cascading configuration** — global defaults in `config.ini` with per-host overrides in `hosts.csv`
- **Bash completion** — tab-complete hostnames on the command line
- **Directory-scoped config** — keep multiple inventories in different folders, `cd` into the desired one before running
- **Installable Python package** — `pip install` and use the `sshmngr` command anywhere

---

## Requirements

- Python >= 3.8
- [Paramiko](https://www.paramiko.org/) >= 3.0

---

## Installation

### From source

```bash
git clone https://github.com/silveX89/sshmngr.git
cd sshmngr
```

Create a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
```

Install the package:

```bash
pip install .           # standard install
# or
pip install -e .        # editable / development install
```

This exposes the `sshmngr` command on your `PATH` (within the venv).

### Bash completion

**User scope:**

```bash
echo 'source /path/to/repo/completions/sshmngr.bash' >> ~/.bashrc
source ~/.bashrc
```

**System scope:**

```bash
sudo cp completions/sshmngr.bash /etc/bash_completion.d/sshmngr
source /etc/bash_completion.d/sshmngr
```

---

## Quick start

1. Copy the example files into a working directory:

   ```bash
   mkdir ~/my-servers && cd ~/my-servers
   cp /path/to/repo/config.ini.example config.ini
   cp /path/to/repo/hosts.csv.example  hosts.csv
   ```

2. Edit `config.ini` and `hosts.csv` to match your environment.

3. Run:

   ```bash
   sshmngr              # interactive host selection
   sshmngr server1      # connect directly by hostname
   ```

---

## Configuration

SSHMngr reads `config.ini` and `hosts.csv` from the **current working directory**. This means you can maintain separate inventories in different folders and simply `cd` into the one you need.

### `config.ini`

INI-style key-value file for global defaults.

| Key | Description | Example |
|---|---|---|
| `global_jumphost` | Use the default jumphost for **all** hosts (`yes` / `no`) | `yes` |
| `jumpserver` | Default jump host address (DNS or IP) | `10.0.0.5` |
| `jumpuser` | Default user for jumphost authentication | `jumpadmin` |
| `ssh_user` | Default SSH username for target hosts | `ubuntu` |

**Example:**

```ini
# Use default jumphost for all connections
global_jumphost = yes

# Jumphost (DNS or IP)
jumpserver = 10.0.0.5

# User for connecting to jumphost
jumpuser = jumpadmin

# Default user for SSH connections
ssh_user = ubuntu
```

If `config.ini` is missing, SSHMngr prints a warning and continues with built-in defaults.

### `hosts.csv`

CSV file with one row per host. The first row must be the header.

| Column | Required | Description |
|---|---|---|
| `hostname` | yes | Unique identifier used for selection and CLI arguments |
| `host` | no | Target IP or DNS name (defaults to `hostname` if empty) |
| `port` | no | SSH port (defaults to `22`) |
| `user` | no | SSH username (overrides `ssh_user` from config) |
| `jumphost` | no | Per-host jump server (overrides `jumpserver` from config) |
| `jumpuser` | no | Per-host jump user (overrides `jumpuser` from config) |
| `notes` | no | Free-text notes |

**Example:**

```csv
hostname,host,port,user,jumphost,jumpuser,notes
server1,192.0.2.10,22,,,,production web server
webserver,198.51.100.20,22,root,,,"needs root access"
firewall,fw.example.net,2222,admin,jump.company.net,jumper,"mgmt via non-std port"
```

### Configuration override hierarchy

Settings are resolved in order of specificity. The first non-empty value wins:

**SSH user:**
1. Per-host `user` column in `hosts.csv`
2. Global `ssh_user` in `config.ini`
3. Interactive prompt at connect time

**Jump host:**
1. Per-host `jumphost` in `hosts.csv` — always used if set
2. Global `jumpserver` in `config.ini` — used only if `global_jumphost = yes`
3. No jump host (direct connection)

**Jump user:**
1. Per-host `jumpuser` in `hosts.csv`
2. Global `jumpuser` in `config.ini`
3. Falls back to the target user

---

## Usage

```
sshmngr [hostname]
```

### Direct connection by name

```bash
sshmngr server1
```

Connects to the host named `server1` from `hosts.csv`. If the name is not found, available hosts are printed.

### Interactive host selection

```bash
sshmngr
```

When no hostname argument is provided:

- **With TTY support:** opens a full-screen TUI (curses-based) with real-time search
- **Without TTY:** falls back to a numbered list prompt

### TUI controls

| Key | Action |
|---|---|
| Type any character | Filter hosts by name in real time |
| `↑` / `↓` | Move selection up/down |
| `Backspace` | Delete last search character |
| `Enter` | Connect to selected host |
| `Esc` | Cancel and exit |

The TUI supports scrolling for large host lists and dynamically adjusts to terminal size.

---

## Authentication

SSHMngr uses [Paramiko](https://www.paramiko.org/) for SSH connections and follows this authentication strategy:

1. **Key / agent authentication** — tries SSH agent keys and local key files first
2. **Password fallback** — if key auth fails, prompts for a password interactively

For jump host connections, if the jumphost was authenticated with a password, the same password is automatically tried for the target host before prompting again.

All connections use a **15-second timeout** and automatically accept unknown host keys (`AutoAddPolicy`).

---

## Architecture

### Project structure

```
sshmngr/
├── sshmngr/
│   ├── __init__.py           # Package init, version, exports
│   └── sshmngr.py            # Main application (all logic)
├── completions/
│   └── sshmngr.bash          # Bash tab-completion script
├── config.ini.example        # Example configuration
├── hosts.csv.example         # Example host inventory
├── pyproject.toml            # Package metadata & build config
└── README.md                 # This file
```

### Code organization (`sshmngr/sshmngr.py`)

The application is organized into three sections:

**Configuration helpers** — functions for reading `config.ini` and `hosts.csv`:
- `read_config()` — parses the INI file into a key-value dict
- `load_hosts()` — parses the CSV into a dict keyed by hostname

**Host selection** — interactive host picking:
- `choose_target()` — dispatcher that selects TUI or numbered-list mode
- `_tui_select_host()` — curses-based full-screen selector with search
- `_prompt_choose_target()` — simple numbered-list fallback

**Connection logic** — SSH connection handling:
- `build_connection_plan()` — resolves all settings (user, port, jumphost) from config + per-host overrides
- `_try_auth_connect()` — key-first auth with password fallback
- `connect_via_jump()` / `_connect_jump()` — jump host connection using `direct-tcpip` channel forwarding
- `_interactive_shell()` — multiplexed terminal I/O via `select()` in raw mode

### Connection flow

```
main()
 ├── read_config() + load_hosts()
 ├── choose_target()                 # if no CLI argument
 ├── build_connection_plan()         # resolve settings
 └── jumphost?
      ├── yes → connect_via_jump()
      │         ├── auth to jumphost
      │         ├── open direct-tcpip channel to target
      │         ├── auth to target through channel
      │         └── _interactive_shell()
      └── no  → direct connection
                ├── _try_auth_connect()
                └── _interactive_shell()
```

---

## License

MIT
