# tmux-remote-sessions

A less painful way to work with remote tmux sessions from a local tmux instance.

## Plugin Use Case

Use local tmux sessions to separate projects or contexts. Some panes may contain
SSH connections to remote tmux sessions.

The aim is to make controlling the remote tmux session less painful. Previously you would have used various tricks to make this work, namely:
- different prefix keys on the local and remote tmux servers
- multiple prefix key presses to interact with the nested session
- unbinding and rebinding the prefix key manually

This plugin's approach is to rebind commands that should be routed to the remote
session and conditionally handle them locally or forward them based on a title
marker emitted by the nested tmux client. This gives a pane-aware equivalent
of manual unbinding and rebinding without requiring repeated prefix keys.

## Installation

Requires tmux 3.7 or newer and `python3`.

### Installation with Tmux Plugin Manager (recommended)

Add the plugin to `.tmux.conf`:

```tmux
set -g @plugin 'ZHDI-1/tmux-remote-sessions'
```

Press prefix + I to fetch the plugin and source it. The local binding generator
uses only the Python standard library. The remote tmux configuration in the
Usage section is also required for title detection.

### Manual Installation

Clone the repository:

```sh
git clone https://github.com/ZHDI-1/tmux-remote-sessions ~/clone/path
```

Add this line to the bottom of `.tmux.conf`:

```tmux
run-shell ~/clone/path/tmux-remote-sessions.tmux
```

Reload `.tmux.conf` with `tmux source-file ~/.tmux.conf`.

## Usage

The local plugin detects nested tmux through a title marker emitted by the
remote tmux client. It does not modify the remote host automatically; add this
configuration to the remote `~/.tmux.conf`:

```tmux
set -g @trs-level pane
set -g set-titles on
set -g set-titles-string 'TRS:#{@trs-level}:remote'

bind-key R if-shell -F '#{==:#{@trs-level},pane}' 'set-option @trs-level window' 'if-shell -F "#{==:#{@trs-level},window}" "set-option @trs-level session" "set-option @trs-level pane"'
```

The remote `R` binding cycles `TRS:pane`, `TRS:window`, and `TRS:session`.
The local `prefix+r` sends `prefix+R` into a recognized remote tmux pane; it
does nothing for a plain SSH shell. The marker travels through SSH and is read
from the active local pane's `#{pane_title}`. A normal SSH shell should use a
different title such as `TRS:shell` so it is not treated as nested tmux. Reset
that title after the remote tmux client detaches. On the local tmux, ensure
title updates are allowed:

```tmux
set -g allow-set-title on
```

Forwarding is hierarchical:

- `TRS:pane` forwards pane and copy/buffer operations such as `split-window`,
  `select-pane`, `resize-pane`, `copy-mode`, and `paste-buffer`.
- `TRS:window` additionally forwards window and layout operations such as
  `next-window`, `select-window`, `new-window`, and `select-layout`.
- `TRS:session` additionally forwards session/client operations.

`prefix+s` always remains local, even at session level, so the outer tmux can
select a local session. Plain SSH sessions remain local unless they emit a
recognized marker.

### Optional local behavior

The plugin remaps Vim-style pane keys (`h`, `j`, `k`, and `l`, including their
Control and Meta variants) to tmux's directional key names when forwarding
them. This is enabled by default. Disable it before loading the plugin if the
remote tmux uses the same Vim-style bindings:

```tmux
set -g @tmux-remote-sessions-vim-navigation off
```

Local `new-window` and `split-window` commands can explicitly inherit the
active pane's working directory. This is disabled by default; enable it before
loading the plugin:

```tmux
set -g @tmux-remote-sessions-preserve-current-path on
```

Commands that already specify `-c` are left unchanged. Both options accept
`on`/`off`, `true`/`false`, `yes`/`no`, or `1`/`0` and take effect when the
plugin is loaded or the tmux configuration is reloaded.

## Future Work

* Make marker names and forwarded command sets configurable.
* Support forwarding selected non-prefix and mouse commands.
* Improve local/remote clipboard integration.

## Known Limitations

* Mouse bindings are not currently forwarded.
* Copy-mode and buffer commands are forwarded, but local and remote clipboards
  are not synchronized automatically. enable ocs52 in your whole path to synchronize
  clipboard

The plugin is intentionally focused on prefix bindings and title-based routing.

## Implementation Details

`generate_bindings.py` reads structured key metadata from `tmux list-keys -F`,
classifies each binding by tmux scope, and owns the install/restore lifecycle. It
emits temporary tmux configuration with carefully quoted conditional commands,
sources it, and stores original bindings in per-installation JSON state. The
`.tmux` file is only the TPM-compatible launcher.

For a quick syntax and unit-test check, run:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n tmux-remote-sessions.tmux
```

## References

Useful alternatives/ references for dealing with remote tmux sessions

- https://simplyian.com/2014/03/29/using-tmux-remotely-within-a-local-tmux-session
- http://stahlke.org/dan/tmux-nested
- https://github.com/samoshkin/tmux-config
- https://github.com/dojoteef/tmux-navigate
