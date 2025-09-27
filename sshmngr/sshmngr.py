#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sshmngr – SSH connection manager with interactive search, autocompletion,
jumphost support, secure credential storage, and logging.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import ipaddress
import logging
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import paramiko
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyWordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import print_formatted_text

try:
    import configparser
except ImportError:
    import ConfigParser as configparser  # type: ignore

try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover
    keyring = None  # type: ignore

APP_NAME = "sshmngr"
CONFIG_DIR = Path(os.path.expanduser("~/.config")) / APP_NAME
CSV_PATH = CONFIG_DIR / "connections.csv"
INI_PATH = CONFIG_DIR / "config.ini"
LOG_PATH = CONFIG_DIR / "sshmngr.log"
DEFAULT_MODE = 0o600

@dataclass(frozen=True)
class HostEntry:
    ip: str
    hostname: str

def ensure_config_files():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _chmod_secure(CONFIG_DIR)

    if not CSV_PATH.exists():
        CSV_PATH.write_text("192.168.1.100,webserver1\n10.0.0.50,database\n", encoding="utf-8")
        _chmod_secure(CSV_PATH)

    if not INI_PATH.exists():
        tmpl = (
            "[users]\n"
            "webserver1 = admin\n"
            "database = dbadmin\n\n"
            "# [keys]\n"
            "# webserver1 = ~/.ssh/id_ed25519\n\n"
            "# [jump]\n"
            "# database = bastion1\n\n"
            "# [jump_users]\n"
            "# bastion1 = jumpadmin\n\n"
            "[options]\n"
            "use_agent = true\n"
        )
        INI_PATH.write_text(tmpl, encoding="utf-8")
        _chmod_secure(INI_PATH)

    _init_logging()

def _chmod_secure(p: Path):
    try:
        os.chmod(p, DEFAULT_MODE if p.is_file() else 0o700)
    except PermissionError:
        pass

def _init_logging():
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        _chmod_secure(LOG_PATH)
    except FileNotFoundError:
        pass

def load_connections() -> List[HostEntry]:
    entries: List[HostEntry] = []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            ip, hostname = row[0].strip(), row[1].strip()
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                continue
            if hostname:
                entries.append(HostEntry(ip=ip, hostname=hostname))
    return entries

def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(INI_PATH)
    return cfg

def resolve_username(cfg: configparser.ConfigParser, hostname: str) -> Optional[str]:
    if cfg.has_section("users") and cfg.has_option("users", hostname):
        return cfg.get("users", hostname).strip() or None
    return None

def resolve_keyfile(cfg: configparser.ConfigParser, hostname: str) -> Optional[Path]:
    if cfg.has_section("keys") and cfg.has_option("keys", hostname):
        p = Path(os.path.expanduser(cfg.get("keys", hostname).strip()))
        return p if p.exists() else None
    return None

def resolve_jump(cfg: configparser.ConfigParser, target_host: str) -> Optional[str]:
    if cfg.has_section("jump") and cfg.has_option("jump", target_host):
        return cfg.get("jump", target_host).strip() or None
    return None

def resolve_jump_user(cfg: configparser.ConfigParser, jumphost: str) -> Optional[str]:
    if cfg.has_section("jump_users") and cfg.has_option("jump_users", jumphost):
        return cfg.get("jump_users", jumphost).strip() or None
    return resolve_username(cfg, jumphost)

def get_option_bool(cfg: configparser.ConfigParser, section: str, key: str, default: bool) -> bool:
    try:
        return cfg.getboolean(section, key, fallback=default)
    except Exception:
        return default

def get_password_from_store(hostname: str, username: str) -> Optional[str]:
    if keyring is None:
        return None
    try:
        return keyring.get_password(APP_NAME, f"{hostname}:{username}")
    except Exception:
        return None

def set_password_in_store(hostname: str, username: str, password: str) -> bool:
    if keyring is None:
        return False
    try:
        keyring.set_password(APP_NAME, f"{hostname}:{username}", password)
        return True
    except Exception:
        return False

def prompt_password(hostname: str, username: str) -> str:
    return getpass.getpass(f"Password for {username}@{hostname}: ")

def error_exit(msg: str, code: int = 2):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)

def interactive_select(hosts: List[HostEntry]) -> HostEntry:
    if not hosts:
        error_exit("No hosts found in connections.csv")

    name_to_host: Dict[str, HostEntry] = {h.hostname: h for h in hosts}
    names = sorted(name_to_host.keys())

    print_formatted_text(HTML("<b>SSHMngr</b> – start typing a hostname, press <b>Enter</b> to connect."))
    print_formatted_text(HTML("Available hosts: " + ", ".join(names)))

    completer = FuzzyWordCompleter(names, WORD=True, ignore_case=True)
    session = PromptSession()
    while True:
        try:
            choice = session.prompt(
                HTML("<skyblue>Host</skyblue>> "),
                completer=completer,
                complete_while_typing=True,
            ).strip()
            if choice in name_to_host:
                return name_to_host[choice]
            matches = [n for n in names if choice.lower() in n.lower()]
            if len(matches) == 1:
                return name_to_host[matches[0]]
            print_formatted_text(HTML(f"<ansired>No such host:</ansired> {choice}"))
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)

class SSHConnector:
    def __init__(self, use_agent: bool = True):
        self.use_agent = use_agent

    def _connect_basic(self, hostname: str, ip: str, username: str,
                       password: Optional[str], key_filename: Optional[Path], sock=None) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs = {
            "hostname": ip,
            "username": username,
            "timeout": 20.0,
            "look_for_keys": self.use_agent,
            "allow_agent": self.use_agent,
        }
        if key_filename:
            kwargs["key_filename"] = str(key_filename)
        if password:
            kwargs["password"] = password
        if sock is not None:
            kwargs["sock"] = sock

        client.connect(**kwargs)
        return client

    def connect_with_optional_jump(self, target: HostEntry, cfg: configparser.ConfigParser
                                  ) -> Tuple[paramiko.SSHClient, Optional[paramiko.SSHClient]]:
        use_agent = get_option_bool(cfg, "options", "use_agent", True)

        target_user = resolve_username(cfg, target.hostname)
        if not target_user:
            error_exit(f"No username found for host '{target.hostname}' in [users]")

        keyfile = resolve_keyfile(cfg, target.hostname)
        password = get_password_from_store(target.hostname, target_user)
        if not password and keyfile is None and not use_agent:
            password = prompt_password(target.hostname, target_user)

        jump_alias = resolve_jump(cfg, target.hostname)
        if not jump_alias:
            target_client = self._connect_basic(
                hostname=target.hostname, ip=target.ip, username=target_user,
                password=password, key_filename=keyfile
            )
            return target_client, None

        all_hosts = load_connections()
        jump_entry = next((h for h in all_hosts if h.hostname == jump_alias), None)
        if not jump_entry:
            error_exit(f"Jumphost '{jump_alias}' not found in connections.csv")

        jump_user = resolve_jump_user(cfg, jump_alias) or target_user
        jump_key = resolve_keyfile(cfg, jump_alias)
        jump_pass = get_password_from_store(jump_alias, jump_user)
        if not jump_pass and jump_key is None and not use_agent:
            jump_pass = prompt_password(jump_alias, jump_user)

        jump_client = self._connect_basic(
            hostname=jump_entry.hostname, ip=jump_entry.ip, username=jump_user,
            password=jump_pass, key_filename=jump_key
        )

        jump_transport = jump_client.get_transport()
        if jump_transport is None or not jump_transport.is_active():
            jump_client.close()
            error_exit("Jump transport unavailable or inactive")

        dest_addr = (target.ip, 22)
        src_addr = ("127.0.0.1", 0)
        chan = jump_transport.open_channel("direct-tcpip", dest_addr, src_addr)

        target_client = self._connect_basic(
            hostname=target.hostname, ip=target.ip, username=target_user,
            password=password, key_filename=keyfile, sock=chan
        )

        return target_client, jump_client

    def start_interactive_shell(self, client: paramiko.SSHClient):
        chan = client.invoke_shell(term=os.environ.get("TERM", "xterm"))
        import select
        import tty
        import termios

        old_tty = termios.tcgetattr(sys.stdin)
        try:
            tty.setraw(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            chan.settimeout(0.0)

            while True:
                r, w, e = select.select([chan, sys.stdin], [], [])
                if chan in r:
                    try:
                        data = chan.recv(1024)
                        if not data:
                            break
                        sys.stdout.buffer.write(data)
                        sys.stdout.flush()
                    except Exception:
                        break
                if sys.stdin in r:
                    x = os.read(sys.stdin.fileno(), 1024)
                    if not x:
                        break
                    chan.send(x)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)
            try:
                chan.close()
            except Exception:
                pass

def export_configs(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    dst_csv = out_dir / "connections.csv"
    dst_ini = out_dir / "config.ini"
    dst_csv.write_text(CSV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    dst_ini.write_text(INI_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    _chmod_secure(dst_csv)
    _chmod_secure(dst_ini)
    print(f"Exported to: {out_dir}")

def import_configs(in_dir: Path):
    src_csv = in_dir / "connections.csv"
    src_ini = in_dir / "config.ini"
    if not src_csv.exists() or not src_ini.exists():
        error_exit("Input folder must contain connections.csv and config.ini")
    CSV_PATH.write_text(src_csv.read_text(encoding="utf-8"), encoding="utf-8")
    INI_PATH.write_text(src_ini.read_text(encoding="utf-8"), encoding="utf-8")
    _chmod_secure(CSV_PATH)
    _chmod_secure(INI_PATH)
    print(f"Imported from: {in_dir}")

COMPLETION_SNIPPET = r"""
# Bash completion for sshmngr (hosts from connections.csv)
_sshmngr_complete()
{
    local cur prev words cword
    _init_completion -n : || return

    local cfg="${HOME}/.config/sshmngr/connections.csv"
    if [[ -f "$cfg" ]]; then
        COMPREPLY=( $( compgen -W "$(cut -d',' -f2 "$cfg" | tr -d '\r' )" -- "$cur" ) )
    else
        COMPREPLY=()
    fi
    return 0
}
complete -F _sshmngr_complete sshmngr
"""

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="sshmngr", description="SSH connection manager")
    p.add_argument("host", nargs="?", help="Hostname alias to connect (from connections.csv)")
    p.add_argument("--export", metavar="DIR", help="Export connections.csv and config.ini to DIR")
    p.add_argument("--import", dest="import_dir", metavar="DIR", help="Import configs from DIR")
    p.add_argument("--store-password", action="store_true", help="Store password in OS keychain for HOST (use with positional HOST)")
    p.add_argument("--print-completion", action="store_true", help="Print bash completion snippet")
    p.add_argument("--version", action="version", version="sshmngr 1.0.0")
    return p.parse_args(argv)

def main(argv: List[str]) -> int:
    ensure_config_files()
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.print_completion:
        print(COMPLETION_SNIPPET.strip())
        return 0

    if args.export:
        export_configs(Path(os.path.expanduser(args.export)))
        return 0

    if args.import_dir:
        import_configs(Path(os.path.expanduser(args.import_dir)))
        return 0

    hosts = load_connections()
    cfg = load_config()

    if args.host and args.store_password:
        target = next((h for h in hosts if h.hostname == args.host), None)
        if not target:
            error_exit(f"Host '{args.host}' not found")
        user = resolve_username(cfg, target.hostname)
        if not user:
            error_exit(f"No username for '{target.hostname}' in [users]")
        pw = prompt_password(target.hostname, user)
        ok = set_password_in_store(target.hostname, user, pw)
        print("Password stored in system keychain." if ok else "Could not store password (keyring unavailable).")
        return 0

    if args.host:
        target = next((h for h in hosts if h.hostname == args.host), None)
        if not target:
            error_exit(f"Host '{args.host}' not found")
    else:
        target = interactive_select(hosts)

    connector = SSHConnector(use_agent=get_option_bool(cfg, "options", "use_agent", True))
    logging.info("Connecting to host='%s' ip='%s'", target.hostname, target.ip)
    try:
        client, jump_client = connector.connect_with_optional_jump(target, cfg)
    except paramiko.AuthenticationException:
        logging.warning("Authentication failed host='%s'", target.hostname)
        error_exit("Authentication failed.")
    except paramiko.SSHException as e:
        logging.error("SSH error host='%s': %s", target.hostname, e)
        error_exit(f"SSH error: {e}")
    except Exception as e:
        logging.error("Unhandled error host='%s': %s", target.hostname, e)
        error_exit(str(e))

    try:
        connector.start_interactive_shell(client)
    finally:
        try:
            client.close()
        except Exception:
            pass
        if jump_client:
            try:
                jump_client.close()
            except Exception:
                pass
        logging.info("Disconnected host='%s'", target.hostname)

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
