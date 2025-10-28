#!/usr/bin/env python3
"""Simple SSH connection helper with optional jumphost support."""

from __future__ import annotations

import csv
import getpass
import os
import sys
from typing import Dict, Iterable, List, Optional, Tuple

import paramiko
from paramiko.ssh_exception import AuthenticationException, SSHException


###############################################################################
# Configuration helpers
###############################################################################

def _project_root() -> str:
    return os.getcwd()


def _config_path() -> str:
    return os.path.join(_project_root(), "config.ini")


def _hosts_path() -> str:
    return os.path.join(_project_root(), "hosts.csv")


def read_config(path: str) -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    if not os.path.exists(path):
        print(f"WARNING: config.ini not found at {path}. Using built-in defaults.")
        return cfg

    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip()
    return cfg


def load_hosts(path: str) -> Dict[str, Dict[str, str]]:
    hosts: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(path):
        print(f"ERROR: hosts.csv not found at {path}")
        return hosts

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("hostname") or "").strip()
            if not name:
                continue
            hosts[name] = {
                "hostname": name,
                "host": (row.get("host") or "").strip(),
                "port": (row.get("port") or "").strip(),
                "user": (row.get("user") or "").strip(),
                "jumphost": (row.get("jumphost") or "").strip(),
                "jumpuser": (row.get("jumpuser") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
            }
    return hosts


###############################################################################
# Host selection helpers
###############################################################################

def _prompt_choose_target(names: Iterable[str]) -> Optional[str]:
    names = list(names)
    print("Available hosts:")
    for idx, name in enumerate(names, 1):
        print(f"  {idx:2d}) {name}")

    try:
        selection = int(input("Select number: ").strip())
    except Exception:
        selection = 0

    if 1 <= selection <= len(names):
        return names[selection - 1]

    print("Invalid selection.")
    return None


def _supports_fullscreen() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _tui_select_host(stdscr, names: List[str]) -> Optional[str]:
    import curses

    try:
        curses.curs_set(1)
    except curses.error:
        pass

    curses.noecho()
    stdscr.keypad(True)

    query = ""
    selected_idx = 0
    scroll_offset = 0

    def _filtered(text: str) -> List[str]:
        lower = text.lower()
        return [name for name in names if lower in name.lower()]

    while True:
        filtered = _filtered(query)
        if not filtered:
            selected_idx = 0
            scroll_offset = 0
        elif selected_idx >= len(filtered):
            selected_idx = len(filtered) - 1

        height, width = stdscr.getmaxyx()
        stdscr.erase()

        prompt = f"Search: {query}"
        prompt_x = max((width - len(prompt)) // 2, 0)
        stdscr.addnstr(0, max(prompt_x, 0), prompt, max(width, 0))
        cursor_x = min(prompt_x + len("Search: ") + len(query), max(width - 1, 0))
        stdscr.move(0, cursor_x)

        list_start_row = 2
        visible_rows = max(0, height - list_start_row)

        if filtered and visible_rows > 0:
            if selected_idx < scroll_offset:
                scroll_offset = selected_idx
            if selected_idx >= scroll_offset + visible_rows:
                scroll_offset = selected_idx - visible_rows + 1

            for row in range(visible_rows):
                idx = scroll_offset + row
                if idx >= len(filtered):
                    break
                name = filtered[idx]
                attr = curses.A_REVERSE if idx == selected_idx else curses.A_NORMAL
                stdscr.addnstr(list_start_row + row, 2, name, max(width - 4, 0), attr)
        elif visible_rows > 0:
            message = "No matching hosts"
            msg_x = max((width - len(message)) // 2, 0)
            stdscr.addnstr(list_start_row, msg_x, message, max(width - msg_x, 0), curses.A_DIM)

        stdscr.refresh()
        key = stdscr.getch()

        if key in (curses.KEY_ENTER, 10, 13):
            if filtered:
                return filtered[selected_idx]
        elif key == 27:  # ESC
            return None
        elif key == curses.KEY_UP:
            if filtered:
                selected_idx = max(0, selected_idx - 1)
        elif key == curses.KEY_DOWN:
            if filtered:
                selected_idx = min(len(filtered) - 1, selected_idx + 1)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if query:
                query = query[:-1]
                selected_idx = 0
                scroll_offset = 0
        elif key == curses.KEY_RESIZE:
            continue
        elif 32 <= key <= 126:
            query += chr(key)
            selected_idx = 0
            scroll_offset = 0


def choose_target(hosts: Dict[str, Dict[str, str]]) -> Optional[str]:
    names = sorted(hosts)
    if not names:
        print("No hosts found in hosts.csv")
        return None

    if _supports_fullscreen():
        try:
            import curses
        except ImportError:
            curses = None
        if curses is not None:
            try:
                return curses.wrapper(lambda stdscr: _tui_select_host(stdscr, names))
            except curses.error:
                pass
            except KeyboardInterrupt:
                return None
    return _prompt_choose_target(names)


###############################################################################
# Connection logic
###############################################################################

def build_connection_plan(cfg: Dict[str, str], host_row: Dict[str, str]) -> Dict[str, Optional[str]]:
    global_jump = cfg.get("global_jumphost", "no").lower() in {"yes", "true", "1"}
    default_jump_host = (cfg.get("jumpserver") or "").strip() or None
    default_jump_user = (cfg.get("jumpuser") or "").strip() or None
    default_user = (cfg.get("ssh_user") or "").strip() or None

    target_host = host_row.get("host") or host_row.get("hostname")
    target_port = host_row.get("port") or "22"
    target_user = host_row.get("user") or default_user

    perhost_jump_host = host_row.get("jumphost") or None
    perhost_jump_user = host_row.get("jumpuser") or None

    jumphost: Optional[str] = None
    jumpuser: Optional[str] = None

    if perhost_jump_host:
        jumphost = perhost_jump_host
        jumpuser = perhost_jump_user or default_jump_user or target_user
    elif global_jump and default_jump_host:
        jumphost = default_jump_host
        jumpuser = default_jump_user or target_user

    return {
        "target_host": target_host,
        "target_port": target_port,
        "target_user": target_user,
        "jumphost": jumphost,
        "jumpuser": jumpuser,
    }


def _try_auth_connect(
    client: paramiko.SSHClient,
    hostname: str,
    port: int,
    username: str,
) -> Tuple[bool, Optional[str]]:
    password_used: Optional[str] = None
    try:
        client.connect(
            hostname=hostname,
            port=port,
            username=username,
            allow_agent=True,
            look_for_keys=True,
            timeout=15,
        )
        return True, None
    except AuthenticationException:
        pw = getpass.getpass(f"Password for {username}@{hostname}: ")
        try:
            client.connect(
                hostname=hostname,
                port=port,
                username=username,
                password=pw,
                allow_agent=False,
                look_for_keys=False,
                timeout=15,
            )
            password_used = pw
            return True, password_used
        except Exception as exc:
            print(f"Authentication failed for {username}@{hostname}: {exc}")
            return False, None
    except Exception as exc:
        print(f"Failed to connect to {username}@{hostname}:{port} - {exc}")
        return False, None


def _connect_jump(
    jumphost: str,
    jumpuser: str,
    target_host: str,
    target_port: int,
    target_user: str,
):
    print(f"Connecting to jumphost {jumpuser}@{jumphost}...")
    jclient = paramiko.SSHClient()
    jclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ok, jump_pw = _try_auth_connect(jclient, jumphost, 22, jumpuser)
    if not ok:
        sys.exit(1)

    transport = jclient.get_transport()
    if not transport:
        print("Failed to obtain transport from jumphost connection")
        jclient.close()
        sys.exit(1)

    dest_addr = (target_host, target_port)
    local_addr = ("", 0)
    try:
        channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)
    except Exception as exc:
        print(f"Failed to open channel to {target_host}:{target_port}: {exc}")
        jclient.close()
        sys.exit(1)

    tclient = paramiko.SSHClient()
    tclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"Connecting to target {target_user}@{target_host}:{target_port} via jumphost...")
    try:
        tclient.connect(
            hostname=target_host,
            port=target_port,
            username=target_user,
            sock=channel,
            allow_agent=True,
            look_for_keys=True,
            timeout=15,
        )
    except AuthenticationException:
        if jump_pw is None:
            pw = getpass.getpass(f"Password for {target_user}@{target_host}: ")
        else:
            pw = jump_pw
        try:
            tclient.connect(
                hostname=target_host,
                port=target_port,
                username=target_user,
                password=pw,
                sock=channel,
                allow_agent=False,
                look_for_keys=False,
                timeout=15,
            )
        except Exception as exc:
            print(f"Failed to authenticate with target {target_user}@{target_host}: {exc}")
            tclient.close()
            jclient.close()
            sys.exit(1)
    except Exception as exc:
        print(f"Failed to connect to target via jumphost: {exc}")
        tclient.close()
        jclient.close()
        sys.exit(1)

    print("Connected. Starting interactive shell...")
    _interactive_shell(tclient)
    tclient.close()
    jclient.close()


def connect_via_jump(
    jumphost: str,
    jumpuser: str,
    target_host: str,
    target_port: int,
    target_user: str,
):
    try:
        _connect_jump(jumphost, jumpuser, target_host, target_port, target_user)
    except SSHException as exc:
        print(f"SSH error: {exc}")
        sys.exit(1)


def _interactive_shell(client: paramiko.SSHClient) -> None:
    try:
        channel = client.invoke_shell()
        import select
        import termios
        import tty

        oldtty = termios.tcgetattr(sys.stdin)
        try:
            tty.setraw(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            channel.settimeout(0.0)

            while True:
                readable, _, _ = select.select([channel, sys.stdin], [], [])
                if channel in readable:
                    try:
                        data = channel.recv(1024)
                        if not data:
                            break
                        sys.stdout.write(data.decode(errors="ignore"))
                        sys.stdout.flush()
                    except Exception:
                        pass
                if sys.stdin in readable:
                    data = os.read(sys.stdin.fileno(), 1024)
                    if not data:
                        break
                    channel.send(data)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, oldtty)
    except Exception as exc:
        print(f"Interactive shell error: {exc}")
    finally:
        client.close()


def main() -> None:
    cfg = read_config(_config_path())
    hosts = load_hosts(_hosts_path())
    if not hosts:
        sys.exit(1)

    if len(sys.argv) >= 2:
        name = sys.argv[1]
        if name not in hosts:
            print(f"Host '{name}' not found in hosts.csv")
            print("Available:", ", ".join(sorted(hosts)))
            sys.exit(1)
        target_name = name
    else:
        target_name = choose_target(hosts)
        if not target_name:
            sys.exit(1)

    plan = build_connection_plan(cfg, hosts[target_name])
    target_host = plan["target_host"]
    target_port = int(plan["target_port"] or "22")
    target_user = plan["target_user"]
    jumphost = plan["jumphost"]
    jumpuser = plan["jumpuser"]

    if not target_host:
        print("No target host/IP specified for the selected entry.")
        sys.exit(1)

    if not target_user:
        target_user = input("No user found. Please enter SSH username for target: ").strip()

    if jumphost:
        connect_via_jump(jumphost, jumpuser or target_user, target_host, target_port, target_user)
    else:
        print(f"Connecting directly to {target_user}@{target_host}:{target_port}")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ok, _ = _try_auth_connect(client, target_host, target_port, target_user)
        if not ok:
            sys.exit(1)
        print(f"Connected to {target_user}@{target_host}. Starting interactive shell...")
        _interactive_shell(client)


if __name__ == "__main__":
    main()
