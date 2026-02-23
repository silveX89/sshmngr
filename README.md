# SSHMngr

A tiny SSH connection helper with optional jump host support and simple CSV-driven inventory.

## What’s new (2025-09-28)
- `pyproject.toml` added: installable package with a **console command** `sshmngr`.
- **Defaults in config**: default SSH user, default jumphost and its user.
- **Global vs per-host jump** via `global_jumphost = yes|no`.
- **Per-host overrides** via `hosts.csv`.
- **Password fallback** if key/agent auth fails.
- **Config & inventory read from the current working directory** (the directory where you run `sshmngr`).

---

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install .           # or: pip install -e . for editable
```

This exposes the `sshmngr` command on your PATH (within the venv).

## Files expected in your *current working directory*

- `config.ini` – global settings
- `hosts.csv`  – inventory of hosts (with optional per-host overrides)

> Tip: Keep multiple inventories in different folders. `cd` into the folder containing the desired config before running `sshmngr`.

### `config.ini` format

```ini
#use default jumphost for all connections
global_jumphost = yes

#jumphost (dns or ip)
jumpserver = 10.0.0.5

#user for connecting to jumphost
jumpuser = jumpadmin

#default user for ssh connections
ssh_user = ubuntu

#host specific custom settings
# insert variables for custom settings
```

### `hosts.csv` format

```csv
hostname,host,port,user,jumphost,jumpuser,notes
coruscant,192.0.2.10,22,,,
bespin,198.51.100.20,22,root,,
firewall,fw.example.net,2222,admin,jump.company.net,jumper,"mgmt via non-std port"
```

- `user` overrides `ssh_user`.
- `jumphost`/`jumpuser` override `jumpserver`/`jumpuser` from `config.ini`.
- If `global_jumphost = yes`, the default `jumpserver` is used unless a row sets its own `jumphost`.
- If `global_jumphost = no`, a jumphost is used only when set per-host.

## Repository hygiene

A preconfigured `.gitignore` keeps build artifacts, virtual environments, caches, and OS/editor files out of your repo. By default it **does not** ignore `config.ini` and `hosts.csv` so you can version example files; uncomment those lines in `.gitignore` if you prefer to keep operational configs out of Git.

## License
MIT

