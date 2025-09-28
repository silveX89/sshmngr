#!/usr/bin/env python3
"""
SSHMngr: Simple SSH helper with optional jumphost (Paramiko-based).

- Config & inventory loaded from current working directory (config.ini, hosts.csv).
- Defaults: ssh_user (targets), jumpserver & jumpuser (jumphost).
- global_jumphost: yes|no to force default jumpserver for all targets (unless overridden per-host).
- Per-host overrides via hosts.csv: user, jumphost, jumpuser, port.
- Password fallback prompts if key/agent auth fails (for jumphost and/or target).
"""

import csv
import os
import sys
import socket
import getpass
from typing import Dict, Optional, Tuple

import paramiko
from paramiko.ssh_exception import AuthenticationException, SSHException

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
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg

def load_hosts(path: str) -> Dict[str, Dict[str, str]]:
    hosts: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(path):
        print(f"ERROR: hosts.csv not found at {path}")
        return hosts
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("hostname") or "").strip()
            if not name:
                continue
            entry = {
                "hostname": name,
                "host": (row.get("host") or "").strip(),
                "port": (row.get("port") or "").strip(),
                "user": (row.get("user") or "").strip(),
                "jumphost": (row.get("jumphost") or "").strip(),
                "jumpuser": (row.get("jumpuser") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
            }
            hosts[name] = entry
    return hosts

def choose_target(hosts):
    names = sorted(hosts.keys())
    if not names:
        print("No hosts found in hosts.csv")
        return None
    print("Available hosts:")
    for i, n in enumerate(names, 1):
        print(f"  {i:2d}) {n}")
    try:
        idx = int(input("Select number: ").strip())
        if 1 <= idx <= len(names):
            return names[idx-1]
    except Exception:
        pass
    print("Invalid selection.")
    return None

def build_connection_plan(cfg, host_row):
    global_jump = (cfg.get("global_jumphost","no").lower() in ["yes","true","1"])
    default_jump_host = cfg.get("jumpserver","").strip() or None
    default_jump_user = cfg.get("jumpuser","").strip() or None
    default_user = cfg.get("ssh_user","").strip() or None

    target_host = host_row.get("host") or host_row.get("hostname")
    target_port = int(host_row.get("port") or "22")
    target_user = host_row.get("user") or default_user

    perhost_jump_host = host_row.get("jumphost") or None
    perhost_jump_user = host_row.get("jumpuser") or None

    jumphost = None
    jumpuser = None
    if perhost_jump_host:
        jumphost = perhost_jump_host
        jumpuser = perhost_jump_user or default_jump_user or target_user
    elif global_jump and default_jump_host:
        jumphost = default_jump_host
        jumpuser = default_jump_user or target_user

    return {
        "target_host": target_host,
        "target_port": str(target_port),
        "target_user": target_user,
        "jumphost": jumphost,
        "jumpuser": jumpuser,
    }

def _try_auth_connect(client: paramiko.SSHClient, hostname: str, port: int, username: str):
    pw_used = None
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
            pw_used = pw
            return True, pw_used
        except Exception as e2:
            print(f"Authentication failed for {username}@{hostname}: {e2}")
            return False, None
    except Exception as e:
        print(f"Connection error to {hostname}:{port} as {username}: {e}")
        return False, None

def connect_via_jump(jumphost: str, jumpuser: str, target_host: str, target_port: int, target_user: str):
    print(f"Using jumphost {jumpuser}@{jumphost} -> {target_user}@{target_host}:{target_port}")
    jclient = paramiko.SSHClient()
    jclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ok, _ = _try_auth_connect(jclient, jumphost, 22, jumpuser)
    if not ok:
        sys.exit(1)

    try:
        transport = jclient.get_transport()
        if transport is None or not transport.is_active():
            raise SSHException("Jumphost transport is not active.")
        dest = (target_host, target_port)
        src = ("127.0.0.1", 0)
        chan = transport.open_channel("direct-tcpip", dest, src)
    except Exception as e:
        print(f"Failed to open channel from jumphost to {target_host}:{target_port}: {e}")
        jclient.close()
        sys.exit(1)

    tclient = paramiko.SSHClient()
    tclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        tclient.connect(
            hostname=target_host,
            port=target_port,
            username=target_user,
            sock=chan,
            allow_agent=True,
            look_for_keys=True,
            timeout=15,
        )
        print(f"Connected to {target_user}@{target_host} (via jumphost). Starting interactive shell...")
        _interactive_shell(tclient)
    except AuthenticationException:
        pw = getpass.getpass(f"Password for {target_user}@{target_host}: ")
        try:
            tclient.connect(
                hostname=target_host,
                port=target_port,
                username=target_user,
                password=pw,
                sock=chan,
                allow_agent=False,
                look_for_keys=False,
                timeout=15,
            )
            print(f"Connected to {target_user}@{target_host} (via jumphost). Starting interactive shell...")
            _interactive_shell(tclient)
        except Exception as e2:
            print(f"Authentication failed on target {target_user}@{target_host}: {e2}")
            tclient.close()
            jclient.close()
            sys.exit(1)
    except Exception as e:
        print(f"Error connecting to target over jumphost: {e}")
        tclient.close()
        jclient.close()
        sys.exit(1)

def _interactive_shell(client: paramiko.SSHClient):
    try:
        chan = client.invoke_shell()
        import select
        import termios
        import tty
        oldtty = termios.tcgetattr(sys.stdin)
        try:
            tty.setraw(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            chan.settimeout(0.0)
            while True:
                r, w, e = select.select([chan, sys.stdin], [], [])
                if chan in r:
                    try:
                        x = chan.recv(1024)
                        if len(x) == 0:
                            break
                        sys.stdout.write(x.decode(errors="ignore"))
                        sys.stdout.flush()
                    except Exception:
                        pass
                if sys.stdin in r:
                    x = os.read(sys.stdin.fileno(), 1024)
                    if len(x) == 0:
                        break
                    chan.send(x)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, oldtty)
    except Exception as e:
        print(f"Interactive shell error: {e}")
    finally:
        client.close()

def main():
    cfg = read_config(_config_path())
    hosts = load_hosts(_hosts_path())
    if not hosts:
        sys.exit(1)

    if len(sys.argv) >= 2:
        name = sys.argv[1]
        if name not in hosts:
            print(f"Host '{name}' not found in hosts.csv")
            print("Available:", ", ".join(sorted(hosts.keys())))
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
