#!/usr/bin/env python3
"""Generate conditional tmux bindings for nested remote tmux sessions."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


SEPARATOR = "\x1f"
STATE_VERSION = 2
LOCAL_KEYS = frozenset(("r", "s"))
LOCAL_CYCLE_KEY = "r"


class BindingLevel(IntEnum):
    PANE = 1
    WINDOW = 2
    SESSION = 3


PANE_COMMANDS = {
    "break-pane",
    "choose-buffer",
    "clock-mode",
    "copy-mode",
    "delete-buffer",
    "display-message",
    "display-panes",
    "kill-pane",
    "last-pane",
    "list-buffers",
    "paste-buffer",
    "resize-pane",
    "rotate-pane",
    "select-pane",
    "split-window",
    "swap-pane",
}

WINDOW_COMMANDS = {
    "find-window",
    "kill-window",
    "last-window",
    "move-window",
    "new-window",
    "next-layout",
    "next-window",
    "previous-layout",
    "previous-window",
    "rename-window",
    "rotate-window",
    "select-layout",
    "select-window",
    "swap-window",
}

SESSION_COMMANDS = {
    "attach-session",
    "choose-client",
    "detach-client",
    "kill-session",
    "last-session",
    "new-session",
    "next-session",
    "previous-session",
    "rename-session",
    "switch-client",
}


TITLE_PATTERNS = {
    BindingLevel.PANE: "TRS:pane*",
    BindingLevel.WINDOW: "TRS:window*",
    BindingLevel.SESSION: "TRS:session*",
}


class GeneratorError(RuntimeError):
    """Raised when tmux binding input or state is invalid."""


@dataclass(frozen=True)
class Binding:
    table: str
    key: str
    repeat: bool
    note: str
    command: str


@dataclass(frozen=True)
class BindingState:
    bindings: List[Binding]
    local_bindings: List[Binding]


def tmux_quote(value: str) -> str:
    """Quote one tmux command argument without allowing reparsing surprises.

    tmux expands variables and escape sequences inside double quotes. Escaping
    backslashes, double quotes, and dollar signs preserves the value while
    keeping semicolons, braces, hashes, tildes, and whitespace in one token.
    """

    if "\n" in value or "\r" in value:
        raise GeneratorError("multiline tmux arguments are not supported")

    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace("$", "\\$")
    return '"' + escaped + '"'


def parse_bindings(text: str, default_table: str = "prefix") -> List[Binding]:
    """Parse the delimiter-separated output from ``tmux list-keys -F``."""

    bindings: List[Binding] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        fields = line.split(SEPARATOR, 4)
        if len(fields) != 5:
            raise GeneratorError(
                "invalid list-keys record on line {}: expected 5 fields".format(
                    line_number
                )
            )

        table, key, repeat, note, command = fields
        bindings.append(
            Binding(
                table=table or default_table,
                key=key,
                repeat=repeat == "1",
                note=note,
                command=command,
            )
        )
    return bindings


def query_bindings(table: str) -> List[Binding]:
    """Read key bindings using tmux's structured format interface."""

    format_string = SEPARATOR.join(
        ("#{key_table}", "#{key_string}", "#{key_repeat}", "#{key_note}", "#{key_command}")
    )
    result = subprocess.run(
        ["tmux", "list-keys", "-T", table, "-F", format_string],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "tmux list-keys failed"
        raise GeneratorError(message)
    return parse_bindings(result.stdout, default_table=table)


def unquoted_tokens(command: str) -> List[str]:
    """Return tmux-like unquoted tokens, including tokens inside braces.

    This is deliberately only a classifier lexer, not a second tmux parser.
    Quoted prompt text and shell commands are ignored so words such as
    ``kill-window`` inside a prompt do not accidentally select a level.
    """

    tokens: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    index = 0

    def flush() -> None:
        if current:
            tokens.append("".join(current))
            current.clear()

    while index < len(command):
        char = command[index]
        if quote is not None:
            if char == "\\" and index + 1 < len(command):
                index += 2
            elif char == quote:
                quote = None
                index += 1
            else:
                index += 1
            continue

        if char in ("'", '"'):
            flush()
            quote = char
            index += 1
        elif char == "\\" and index + 1 < len(command):
            current.append(command[index + 1])
            index += 2
        elif char.isspace() or char in "{};":
            flush()
            index += 1
        else:
            current.append(char)
            index += 1

    if quote is not None:
        raise GeneratorError("unterminated quote in tmux binding: {}".format(command))
    flush()
    return tokens


def choose_tree_level(tokens: Sequence[str], index: int) -> BindingLevel:
    """Classify choose-tree using its session/window selector flags."""

    for argument in tokens[index + 1 :]:
        if not argument.startswith("-") or argument == "-":
            continue
        flags = argument.lstrip("-")
        if "s" in flags:
            return BindingLevel.SESSION
        if "w" in flags:
            return BindingLevel.WINDOW
    return BindingLevel.SESSION


def command_level(command: str) -> Optional[BindingLevel]:
    """Return the highest forwarding level represented by a binding."""

    tokens = unquoted_tokens(command)
    if not tokens:
        return None

    # Menus contain many nested commands and are intentionally left local.
    if tokens[0] == "display-menu":
        return None

    # Avoid wrapping an already generated binding if a caller applies without
    # first restoring its saved state.
    if tokens[0] == "if-shell" and "TRS:" in command:
        return None

    levels: List[BindingLevel] = []
    for index, token in enumerate(tokens):
        if token == "choose-tree":
            levels.append(choose_tree_level(tokens, index))
        elif token in PANE_COMMANDS:
            levels.append(BindingLevel.PANE)
        elif token in WINDOW_COMMANDS:
            levels.append(BindingLevel.WINDOW)
        elif token in SESSION_COMMANDS:
            levels.append(BindingLevel.SESSION)

    return max(levels) if levels else None


def title_condition(level: BindingLevel) -> str:
    """Build a format condition for a title level or a higher level."""

    patterns = [
        "#{m:" + TITLE_PATTERNS[candidate] + ",#{pane_title}}"
        for candidate in BindingLevel
        if candidate >= level
    ]
    return "#{||:" + ",".join(patterns) + "}"


def send_key_for(key: str) -> str:
    """Translate outer tmux navigation keys to inner tmux key names."""

    return {
        "h": "Left",
        "l": "Right",
        "j": "Down",
        "k": "Up",
        "C-h": "C-Left",
        "C-l": "C-Right",
        "C-j": "C-Down",
        "C-k": "C-Up",
        "M-h": "M-Left",
        "M-l": "M-Right",
        "M-j": "M-Down",
        "M-k": "M-Up",
        "o": "l",
    }.get(key, key)


def binding_options(binding: Binding) -> str:
    options = []
    if binding.repeat:
        options.append("-r")
    options.extend(("-T", tmux_quote(binding.table)))
    if binding.note:
        options.extend(("-N", tmux_quote(binding.note)))
    return " ".join(options)


def render_bind(binding: Binding, command: str) -> str:
    return "bind-key {} {} {}".format(
        binding_options(binding), tmux_quote(binding.key), command
    )


def render_unbind(binding: Binding) -> str:
    return "unbind-key -T {} {}".format(
        tmux_quote(binding.table), tmux_quote(binding.key)
    )


def render_apply(bindings: Iterable[Binding]) -> str:
    """Render only bindings whose operations are eligible for forwarding."""

    lines: List[str] = []
    for binding in bindings:
        level = command_level(binding.command)
        if level is None or binding.key in LOCAL_KEYS:
            continue

        condition = title_condition(level)
        send_command = "send-prefix ; send-keys {}".format(
            tmux_quote(send_key_for(binding.key))
        )
        wrapped = "if-shell -F {} {} {}".format(
            tmux_quote(condition),
            tmux_quote(send_command),
            tmux_quote(binding.command),
        )
        lines.extend((render_unbind(binding), render_bind(binding, wrapped)))

    return "\n".join(lines) + ("\n" if lines else "")


def render_cycle_binding() -> str:
    """Render the local key that asks a nested tmux to cycle its title."""

    binding = Binding("prefix", LOCAL_CYCLE_KEY, False, "", "")
    command = "if-shell -F {} {} {}".format(
        tmux_quote(title_condition(BindingLevel.PANE)),
        tmux_quote("send-prefix; send-keys R"),
        tmux_quote('display-message "not a recognized remote tmux pane"'),
    )
    return "\n".join((render_unbind(binding), render_bind(binding, command))) + "\n"


def render_plugin_config(bindings: Iterable[Binding]) -> str:
    """Render remote forwarding bindings and the local cycle binding."""

    return render_apply(bindings) + render_cycle_binding()


def managed_bindings(bindings: Iterable[Binding]) -> List[Binding]:
    """Return the original records that apply mode will replace."""

    return [
        binding
        for binding in bindings
        if command_level(binding.command) is not None
        and binding.key not in LOCAL_KEYS
    ]


def local_bindings(bindings: Iterable[Binding]) -> List[Binding]:
    """Return original bindings replaced by plugin-owned local keys."""

    return [binding for binding in bindings if binding.key == LOCAL_CYCLE_KEY]


def render_restore(
    bindings: Iterable[Binding], local: Iterable[Binding] = ()
) -> str:
    lines: List[str] = [
        render_unbind(Binding("prefix", LOCAL_CYCLE_KEY, False, "", ""))
    ]
    for binding in bindings:
        lines.extend((render_unbind(binding), render_bind(binding, tmux_quote(binding.command))))
    for binding in local:
        lines.extend((render_unbind(binding), render_bind(binding, tmux_quote(binding.command))))
    return "\n".join(lines) + ("\n" if lines else "")


def write_state(
    path: str,
    bindings: Sequence[Binding],
    local: Sequence[Binding] = (),
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "bindings": [asdict(binding) for binding in bindings],
        "local_bindings": [asdict(binding) for binding in local],
    }

    fd, temporary = tempfile.mkstemp(
        prefix=".{}-".format(destination.name),
        dir=str(destination.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def read_state(path: str) -> BindingState:
    try:
        with open(path, encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise GeneratorError("could not read binding state {}: {}".format(path, error))

    if not isinstance(payload, dict) or payload.get("version") not in (1, STATE_VERSION):
        raise GeneratorError("unsupported binding state version")

    try:
        records = payload["bindings"]
        if not isinstance(records, list):
            raise TypeError("bindings must be a list")
        local_records = payload.get("local_bindings", [])
        if not isinstance(local_records, list):
            raise TypeError("local_bindings must be a list")
        return BindingState(
            bindings=[Binding(**record) for record in records],
            local_bindings=[Binding(**record) for record in local_records],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise GeneratorError("invalid binding state: {}".format(error))


INSTALLED_OPTION = "@tmux-remote-sessions-installed"
STATE_FILE_OPTION = "@tmux-remote-sessions-state-file"
GENERATED_STATE_PREFIX = "tmux-remote-sessions."


def run_tmux(arguments: Sequence[str]) -> str:
    result = subprocess.run(
        ["tmux", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "tmux command failed"
        raise GeneratorError(message)
    return result.stdout


def tmux_option(name: str) -> str:
    return run_tmux(["show-option", "-gqv", name]).strip()


def set_tmux_option(name: str, value: str) -> None:
    run_tmux(["set-option", "-g", name, value])


def source_config(path: Path) -> None:
    run_tmux(["source-file", str(path)])


def write_temporary_config(contents: str, prefix: str) -> Path:
    descriptor, filename = tempfile.mkstemp(prefix=prefix, text=True)
    path = Path(filename)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(contents)
    return path


def remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def remove_generated_state(path: Path) -> None:
    """Remove only state directories created by this plugin."""

    if path.name != "bindings.json" or not path.parent.name.startswith(
        GENERATED_STATE_PREFIX
    ):
        return
    remove_file(path)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def restore_installed_bindings() -> None:
    state_filename = tmux_option(STATE_FILE_OPTION)
    if not state_filename or not Path(state_filename).is_file():
        raise GeneratorError("installed bindings have no restorable Python state")

    state_path = Path(state_filename)
    state = read_state(str(state_path))
    config_path = write_temporary_config(
        render_restore(state.bindings, state.local_bindings),
        "tmux-remote-sessions-restore.",
    )
    try:
        source_config(config_path)
    finally:
        remove_file(config_path)

    remove_generated_state(state_path)
    set_tmux_option(INSTALLED_OPTION, "")
    set_tmux_option(STATE_FILE_OPTION, "")


def install_bindings(table: str) -> None:
    if tmux_option(INSTALLED_OPTION):
        restore_installed_bindings()

    bindings = query_bindings(table)
    state_path = Path(tempfile.mkdtemp(prefix=GENERATED_STATE_PREFIX)) / "bindings.json"
    config_path: Optional[Path] = None
    keep_state = False
    try:
        write_state(
            str(state_path),
            managed_bindings(bindings),
            local_bindings(bindings),
        )
        config_path = write_temporary_config(
            render_plugin_config(bindings),
            "tmux-remote-sessions-config.",
        )
        source_config(config_path)
        set_tmux_option(STATE_FILE_OPTION, str(state_path))
        set_tmux_option(INSTALLED_OPTION, "true")
        run_tmux(["display-message", "applied remote session key bindings"])
        keep_state = True
    finally:
        if config_path is not None:
            remove_file(config_path)
        if not keep_state:
            remove_generated_state(state_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("install", "apply", "restore"))
    parser.add_argument("--table", default="prefix")
    parser.add_argument(
        "--state-out", help="write the original managed bindings to this JSON file"
    )
    parser.add_argument("--state-in", help="read original managed bindings from this JSON file")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "install":
            install_bindings(args.table)
        elif args.mode == "apply":
            bindings = query_bindings(args.table)
            if args.state_out:
                write_state(
                    args.state_out,
                    managed_bindings(bindings),
                    local_bindings(bindings),
                )
            sys.stdout.write(render_apply(bindings))
        else:
            if not args.state_in:
                raise GeneratorError("restore requires --state-in")
            state = read_state(args.state_in)
            sys.stdout.write(render_restore(state.bindings, state.local_bindings))
    except GeneratorError as error:
        print("generate_bindings.py: {}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
