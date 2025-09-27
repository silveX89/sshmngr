# sshmngr

`sshmngr` is a lightweight SSH connection manager written in Python.  
It provides a searchable list of saved SSH connections, quick hostname lookup, and support for jump hosts.

---

## Features

- Store connections in a simple CSV format (`IP,Hostname`)
- Usernames stored in a separate config file
- Secure credential handling
- Jumphost support
- Tab autocompletion for hostnames
- Error handling for missing hosts
- Logging of connection attempts

---

## Installation

Clone the repository:

```bash
git clone https://github.com/silveX89/sshmngr.git
cd sshmngr
```

Install inside a Python virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
pip install .
```

Alternatively, install system-wide (not recommended):

```bash
pip install .
```

---

## Configuration

By default, configuration files are stored in:

```
~/.config/sshmngr/
```

- `hosts.csv` – Stores connections in the format:

  ```
  192.168.1.10,myserver
  10.0.0.5,db01
  ```

- `config.json` – Stores global settings, e.g.:

  ```json
  {
    "default_user": "user",
    "jumphosts": {
      "db01": "jumphost.example.com"
    }
  }
  ```

---

## Usage

Start `sshmngr` without arguments to see all hosts:

```bash
sshmngr
```

Connect directly to a host:

```bash
sshmngr myserver
```

Search for hosts (fuzzy search):

```bash
sshmngr search db
```

With a jumphost:

```bash
sshmngr db01
```
*(will automatically connect via `jumphost.example.com` if configured)*

---

## Autocompletion

To enable tab completion for hostnames, add the following to your shell config:

**Bash (`~/.bashrc`):**
```bash
eval "$(sshmngr --completion bash)"
```

**Zsh (`~/.zshrc`):**
```bash
eval "$(sshmngr --completion zsh)"
```

---

## Logging

All connection attempts are logged to:

```
~/.config/sshmngr/sshmngr.log
```

---

## Roadmap

- Encrypted credentials storage
- Interactive connection selection with arrow keys
- Integration with SSH agent


