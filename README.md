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

Install locally. Requires tmux 3.7 or newer and `python3` on the local host.

### Installation with Tmux Plugin Manager (recommended)

Add the plugin to `.tmux.conf`:

```tmux
set -g @plugin 'ZHDI-1/tmux-remote-sessions'
```

Press prefix + I to fetch the plugin and source it. The local binding generator
uses only the Python standard library. Configure the remote tmux as described
below as well.

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

Install the plugin on the **local host only**. The remote host needs only tmux
and the configuration below; no plugin, Python, or helper script is required.

### Remote configuration

Add this to the remote `~/.tmux.conf`, replacing the old `bind-key R` line if
present:

```tmux
set -g @trs-level pane
set -g set-titles on
set -g set-titles-string 'TRS:#{@trs-level}:remote'

bind-key R set-option -F @trs-level '#{?#{==:#{@trs-level},pane},window,pane}'
bind-key C-r if-shell -F '#{==:#{@trs-level},session}' 'set-option -F @trs-level "#{?#{==:#{@trs-return-level},window},window,pane}"' 'set-option -F @trs-return-level "#{@trs-level}" ; set-option @trs-level session'
```

Reload the remote configuration with `tmux source-file ~/.tmux.conf`.
With this snippet, use these shortcuts from your **local tmux**:

| Shortcut | Action |
| --- | --- |
| `prefix+r` | Toggle remote pane/window scope; from session scope, return to pane. |
| `prefix+Shift+r` (`prefix+R`) | Enter remote session scope; press again to return to the previous pane/window scope. |
| `prefix+s` | Always select a local session. |

The local scope shortcuts send remote `prefix+R` and `prefix+Ctrl+r`,
respectively. The remote bindings change `@trs-level`, which updates the title
seen by the local plugin. Existing remote configurations with only the old
three-level `R` binding still work with local `prefix+r`; add the `C-r` binding
to use the separate session shortcut.

On the **local** tmux, allow title updates:

```tmux
set -g allow-set-title on
```

The marker travels through SSH and is read from the active local pane's
`#{pane_title}`. A plain SSH shell should use a different title such as
`TRS:shell`, and reset that title after the remote tmux client detaches. Both
scope shortcuts require a recognized remote title; otherwise they only show a
local message.

Forwarding is hierarchical:

- `TRS:pane` forwards pane and copy/buffer operations such as `split-window`,
  `select-pane`, `resize-pane`, `copy-mode`, and `paste-buffer`.
- `TRS:window` additionally forwards window and layout operations such as
  `next-window`, `select-window`, `new-window`, and `select-layout`.
- `TRS:session` additionally forwards session/client operations.

`prefix+s` always remains local, even at session level. Plain SSH sessions
remain local unless they emit a recognized marker.

### Three-level cycling

If you prefer the original pane → window → session → pane cycle, replace the
remote `bind-key R` line with this one. The separate session shortcut still
works:

```tmux
bind-key R if-shell -F '#{!=:#{@trs-level},session}' 'set-option -F @trs-return-level "#{@trs-level}" ; set-option -F @trs-level "#{?#{==:#{@trs-level},pane},window,#{?#{==:#{@trs-level},window},session,pane}}"' 'set-option @trs-level pane'
```

### Local options

The plugin remaps Vim-style pane keys (`h`, `j`, `k`, and `l`, including their
Control and Meta variants) to tmux's directional key names when forwarding
them. This is enabled by default. Disable it before loading the local plugin
if the remote tmux uses the same Vim-style bindings:

```tmux
set -g @tmux-remote-sessions-vim-navigation off
```

Local `new-window` and `split-window` bindings can inherit the active local
pane's working directory. This is disabled by default; enable it before loading
the local plugin:

```tmux
set -g @tmux-remote-sessions-preserve-current-path on
```

Commands that already specify `-c` are left unchanged. Both options accept
`on`/`off`, `true`/`false`, `yes`/`no`, or `1`/`0` and take effect when the
plugin is loaded or the local tmux configuration is reloaded.

### Remote working directories

For the same directory-preserving behavior remotely, add these three bindings
to the remote `~/.tmux.conf`:

```tmux
bind-key c new-window -c '#{pane_current_path}'
bind-key % split-window -h -c '#{pane_current_path}'
bind-key '"' split-window -c '#{pane_current_path}'
```

Reload the remote configuration. These bindings resolve the **remote pane's
current directory when pressed**, including when forwarded from local tmux.
Splits are forwarded at every recognized level; `new-window` is forwarded at
window/session level and stays local at pane level.

If you already customize these keys, add `-c '#{pane_current_path}'` to your
existing creation commands instead of replacing them. Keep any explicit `-c`
directory you want to preserve.

The local `@tmux-remote-sessions-preserve-current-path` option controls local
commands only. Forwarding sends keypresses, so remote path behavior is configured
by these remote bindings independently; no remote plugin options are needed.

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

Reload restores the previous local bindings before applying current options,
including the originals of both scope shortcuts. Remote behavior is defined
entirely by the tmux configuration snippets above.

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
