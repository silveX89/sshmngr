#!/usr/bin/env python3
"""sshmngr - SSH connection helper with Claude Code-inspired terminal UI."""
from __future__ import annotations

import configparser
import csv
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ── optional deps ──────────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from rich.rule import Rule
    from rich import box as rich_box
    RICH_OK = True
except ImportError:
    RICH_OK = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import FuzzyWordCompleter
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.styles import Style
    from prompt_toolkit.application.current import get_app
    PROMPT_OK = True
except ImportError:
    PROMPT_OK = False

# ── constants ──────────────────────────────────────────────────────────────────
VERSION = "0.8.0"

_XDG        = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR  = _XDG / "sshmngr"
HOSTS_CSV   = CONFIG_DIR / "hosts.csv"
CONFIG_INI  = CONFIG_DIR / "config.ini"
HISTORY_FILE = CONFIG_DIR / ".history"

# ASCII wizard shown above the header
_WIZARD_LINES = [
    ("  *    ˙    *    ˙    *    ˙    *  ", "bold yellow"),
    ("  ˙    *    ˙    *    ˙    *    ˙  ", "yellow"),
    ("         /\\     /\\               ", "cyan"),
    ("        /  \\___/  \\              ", "cyan"),
    ("       / .-. . .-. \\             ", "cyan"),
    ("      | ( o ) ( o ) |            ", "bold cyan"),
    ("      |   \\ ~~~ /   |            ", "cyan"),
    ("       \\   ~~~~~   /             ", "cyan"),
    ("        \\_________/              ", "cyan"),
    ("            |||||                ", "bold cyan"),
    ("          __||_||__              ", "cyan"),
]


# ── data structures ────────────────────────────────────────────────────────────
@dataclass
class HostEntry:
    hostname: str
    host:     str = ""   # IP or FQDN to connect to
    port:     int = 22
    user:     str = ""   # per-host user override
    jumphost: str = ""   # per-host jump server override
    jumpuser: str = ""   # per-host jump user override
    notes:    str = ""


@dataclass
class Config:
    global_jumphost: bool = False
    jumpserver:      str  = ""
    jumpuser:        str  = ""
    ssh_user:        str  = ""


@dataclass
class CmdFlags:
    """Runtime flags set via slash commands at the prompt."""
    bypass_jumphost: bool = False   # /o  — connect direct, skip all jump logic
    verbose:         bool = False   # /v  — pass -v to ssh
    dry_run:         bool = False   # /d  — print ssh command, do not connect


# ── config / hosts loaders ─────────────────────────────────────────────────────
def _find_file(name: str) -> Optional[Path]:
    """Search CWD first, then ~/.config/sshmngr/."""
    cwd = Path(name)
    if cwd.exists():
        return cwd
    xdg = CONFIG_DIR / name
    if xdg.exists():
        return xdg
    return None


def _preprocess_ini(raw: str) -> str:
    """Make config.ini safe for configparser (add section header, drop bare words)."""
    lines: List[str] = []
    has_section = any(ln.strip().startswith("[") for ln in raw.splitlines())
    if not has_section:
        lines.append("[main]")
    for ln in raw.splitlines():
        stripped = ln.strip()
        # Keep comments, section headers, and key=value lines; drop everything else
        if stripped.startswith(("#", ";")) or stripped.startswith("[") or "=" in stripped:
            lines.append(ln)
    return "\n".join(lines)


def load_config() -> Config:
    cfg = Config()
    path = _find_file("config.ini")
    if path is None:
        return cfg

    raw = path.read_text(encoding="utf-8")
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), strict=False)
    parser.read_string(_preprocess_ini(raw))

    section = parser.sections()[0] if parser.sections() else "main"

    def get(key: str, fallback: str = "") -> str:
        return parser.get(section, key, fallback=fallback).strip()

    cfg.global_jumphost = get("global_jumphost", "no").lower() in ("yes", "true", "1")
    cfg.jumpserver = get("jumpserver")
    cfg.jumpuser   = get("jumpuser")
    cfg.ssh_user   = get("ssh_user")
    return cfg


def load_hosts() -> List[HostEntry]:
    path = _find_file("hosts.csv")
    if path is None:
        return []

    entries: List[HostEntry] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]

        if "hostname" in fieldnames:
            # Full format: hostname,host,port,user,jumphost,jumpuser,notes
            for raw_row in reader:
                row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items() if k}
                hostname = row.get("hostname", "")
                if not hostname or hostname.startswith("#"):
                    continue
                try:
                    port = int(row.get("port") or "22")
                except ValueError:
                    port = 22
                entries.append(HostEntry(
                    hostname=hostname,
                    host=row.get("host", ""),
                    port=port,
                    user=row.get("user", ""),
                    jumphost=row.get("jumphost", ""),
                    jumpuser=row.get("jumpuser", ""),
                    notes=row.get("notes", ""),
                ))
        elif "host" in fieldnames and "addr" in fieldnames:
            # Two-column shorthand: host (alias/name), addr (IP)
            for raw_row in reader:
                row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items() if k}
                hostname = row.get("host", "")
                if not hostname or hostname.startswith("#"):
                    continue
                entries.append(HostEntry(
                    hostname=hostname,
                    host=row.get("addr", ""),
                ))
        elif fieldnames:
            # Any other CSV with a header: treat first column as hostname, second as host/IP
            first_col  = fieldnames[0]
            second_col = fieldnames[1] if len(fieldnames) > 1 else None
            for raw_row in reader:
                row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items() if k}
                hostname = row.get(first_col, "")
                if not hostname or hostname.startswith("#"):
                    continue
                host_ip = row.get(second_col, "") if second_col else ""
                entries.append(HostEntry(hostname=hostname, host=host_ip))
        else:
            # No header — raw lines, first column is hostname
            f.seek(0)
            for row in csv.reader(f):
                if not row:
                    continue
                name = row[0].strip()
                if not name or name.startswith("#"):
                    continue
                entries.append(HostEntry(hostname=name))

    entries.sort(key=lambda e: e.hostname.lower())
    return entries


# ── SSH command builder ────────────────────────────────────────────────────────
def build_ssh_command(entry: HostEntry, config: Config, flags: Optional[CmdFlags] = None) -> List[str]:
    """Build SSH command using ProxyJump (-J) for jump hosts.

    System SSH with -J handles SSH banners from the target host natively,
    avoiding the 'Error reading SSH protocol banner' that occurs with paramiko.
    """
    if flags is None:
        flags = CmdFlags()

    cmd = ["ssh"]

    # Verbose mode (/v)
    if flags.verbose:
        cmd.append("-v")

    # Resolve effective values (per-host overrides global config)
    user     = entry.user     or config.ssh_user
    jumphost = entry.jumphost or (config.jumpserver if config.global_jumphost else "")
    jumpuser = entry.jumpuser or config.jumpuser

    # ProxyJump: handles banner + forwarding transparently
    # Skipped when /o (bypass_jumphost) flag is active
    if jumphost and not flags.bypass_jumphost:
        jump_spec = f"{jumpuser}@{jumphost}" if jumpuser else jumphost
        cmd += ["-J", jump_spec]

    # Non-standard port
    if entry.port and entry.port != 22:
        cmd += ["-p", str(entry.port)]

    # Target: prefer explicit host/IP, fall back to hostname
    target_host = entry.host or entry.hostname
    target = f"{user}@{target_host}" if user else target_host
    cmd.append(target)

    return cmd


# ── slash-command parser ───────────────────────────────────────────────────────
def parse_command(text: str) -> tuple:
    """Strip leading slash-command prefixes and return (host_text, CmdFlags).

    Supported prefixes (stackable, e.g. '/o /v hostname'):
      /o   bypass jumphost — connect directly
      /v   verbose SSH (-v flag)
      /d   dry run — print SSH command without connecting
    """
    flags = CmdFlags()
    text = text.strip()

    while True:
        if text.startswith("/o"):
            flags.bypass_jumphost = True
            text = text[2:].lstrip()
        elif text.startswith("/v"):
            flags.verbose = True
            text = text[2:].lstrip()
        elif text.startswith("/d"):
            flags.dry_run = True
            text = text[2:].lstrip()
        else:
            break

    return text.strip(), flags


# ── UI rendering ───────────────────────────────────────────────────────────────
def _plain_display(entries: List[HostEntry], config: Config) -> None:
    """Fallback display without rich."""
    print(f"\n  sshmngr v{VERSION}")
    if config.jumpserver and config.global_jumphost:
        j = f"{config.jumpuser}@{config.jumpserver}" if config.jumpuser else config.jumpserver
        print(f"  Jump: {j}")
    if config.ssh_user:
        print(f"  User: {config.ssh_user}")
    print()
    for e in entries:
        line = f"  {e.hostname}"
        if e.host:
            line += f"  {e.host}"
        eff_user = e.user or config.ssh_user
        if eff_user:
            line += f"  ({eff_user})"
        if e.notes:
            line += f"  # {e.notes}"
        print(line)
    print()


def display_ui(entries: List[HostEntry], config: Config) -> None:
    """Render the wizard banner, header, and host table."""
    if not RICH_OK:
        _plain_display(entries, config)
        return

    console = Console()
    console.print()

    # ── wizard banner ───────────────────────────────────────────────────────────
    for line_text, line_style in _WIZARD_LINES:
        console.print(f"[{line_style}]{line_text}[/{line_style}]")
    console.print()

    # ── header ─────────────────────────────────────────────────────────────────
    header = Text()
    header.append("sshmngr", style="bold cyan")
    header.append(f"  v{VERSION}", style="dim")

    if config.jumpserver and config.global_jumphost:
        jump_str = (
            f"{config.jumpuser}@{config.jumpserver}"
            if config.jumpuser else config.jumpserver
        )
        header.append("  ·  Jump: ", style="dim")
        header.append(jump_str, style="yellow")

    if config.ssh_user:
        header.append("  ·  User: ", style="dim")
        header.append(config.ssh_user, style="green")

    console.print(header)
    console.print(Rule(style="dim"))
    console.print()

    # ── host table ─────────────────────────────────────────────────────────────
    if not entries:
        console.print(
            "  [dim]No hosts found. Add entries to "
            "~/.config/sshmngr/hosts.csv (or ./hosts.csv)[/dim]"
        )
    else:
        table = Table(
            box=rich_box.SIMPLE,
            show_header=True,
            header_style="bold dim",
            padding=(0, 2),
            show_edge=False,
        )
        table.add_column("Hostname",  style="cyan",          no_wrap=True)
        table.add_column("IP / Host", style="white")
        table.add_column("Port",      style="dim",            justify="right")
        table.add_column("User",      style="green")
        table.add_column("Via Jump",  style="yellow")
        table.add_column("Notes",     style="italic dim")

        for e in entries:
            eff_user = e.user or config.ssh_user or ""
            eff_jump = e.jumphost or (config.jumpserver if config.global_jumphost else "")
            port_str = str(e.port) if e.port != 22 else ""
            table.add_row(e.hostname, e.host, port_str, eff_user, eff_jump, e.notes)

        console.print(table)

    console.print()
    console.print(
        "  [dim]Tab / type to autocomplete  ·  Enter to connect  ·  Ctrl+C to quit[/dim]"
    )
    console.print(
        "  [dim]/o direct  ·  /v verbose  ·  /d dry-run  (stackable, e.g. /o/v)[/dim]"
    )
    console.print()


def show_connect(cmd: List[str], dry_run: bool = False) -> None:
    if not RICH_OK:
        prefix = "  [DRY RUN] " if dry_run else "  Connecting: "
        print(f"{prefix}{' '.join(cmd)}\n")
        return
    console = Console()
    console.print()
    if dry_run:
        label = Text("  Dry run:    ", style="bold yellow")
        label.append(" ".join(cmd), style="yellow")
    else:
        label = Text("  Connecting: ", style="dim")
        label.append(" ".join(cmd), style="cyan")
    console.print(label)
    console.print()


# ── interactive prompt ─────────────────────────────────────────────────────────
def run_prompt(entries: List[HostEntry]) -> tuple:
    """Show interactive prompt; returns (host_text, CmdFlags)."""
    host_names = [e.hostname for e in entries]

    if not PROMPT_OK:
        try:
            raw = input(" > ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            raise SystemExit(130)
        return parse_command(raw)

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.touch(exist_ok=True)

    session: PromptSession = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        style=Style.from_dict({
            "prompt":          "bold cyan",
            "prompt.override": "bold fg:darkorange",
        }),
    )
    completer = FuzzyWordCompleter(words=host_names, WORD=True)

    def _dynamic_prompt():
        """Return prompt tokens; turns orange when a slash command is active."""
        try:
            buf_text = get_app().current_buffer.text
            if buf_text.startswith("/"):
                return [("class:prompt.override", " ⚡ > ")]
        except Exception:
            pass
        return [("class:prompt", " > ")]

    while True:
        try:
            text = session.prompt(
                _dynamic_prompt,
                completer=completer,
                complete_while_typing=True,
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            raise SystemExit(130)
        if text:
            return parse_command(text)


# ── host resolution ────────────────────────────────────────────────────────────
def find_entry(text: str, entries: List[HostEntry]) -> HostEntry:
    """Resolve typed text to the best matching HostEntry."""
    lc = text.lower()
    # Exact hostname match
    for e in entries:
        if e.hostname.lower() == lc:
            return e
    # Unique prefix match
    matches = [e for e in entries if e.hostname.lower().startswith(lc)]
    if len(matches) == 1:
        return matches[0]
    # Exact IP/host match
    for e in entries:
        if e.host.lower() == lc:
            return e
    # Literal fallback (ssh handles unknown hosts natively)
    return HostEntry(hostname=text, host=text)


# ── entry point ────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    argv = argv if argv is not None else sys.argv[1:]
    ap = argparse.ArgumentParser(prog="sshmngr", description="SSH connection helper.")
    ap.add_argument("host",         nargs="?",          help="Connect directly to this host.")
    ap.add_argument("--list-hosts", action="store_true", help="Print known hosts (for shell completion).")
    args = ap.parse_args(argv)

    config  = load_config()
    entries = load_hosts()

    if args.list_hosts:
        for e in entries:
            print(e.hostname)
        return 0

    # Render TUI
    display_ui(entries, config)

    # Get target (from CLI arg or interactive prompt)
    if args.host:
        target_text, flags = parse_command(args.host)
        if not target_text:
            target_text = args.host
    else:
        target_text, flags = run_prompt(entries)

    if not target_text:
        return 1

    entry = find_entry(target_text, entries)
    cmd   = build_ssh_command(entry, config, flags)

    show_connect(cmd, dry_run=flags.dry_run)

    if flags.dry_run:
        return 0

    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        print("Error: 'ssh' not found in PATH.", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
