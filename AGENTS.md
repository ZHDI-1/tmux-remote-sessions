# Repository Guidelines

## Project Structure & Module Organization

This Bash/Python plugin forwards local prefix bindings to nested remote tmux
sessions. Implementation files are at the repository root:

- `tmux-remote-sessions.tmux` is the TPM/run-shell entrypoint and launches the
  Python installer.
- `generate_bindings.py` reads structured `tmux list-keys` data, emits carefully
  quoted conditional bindings, and owns installation/restoration state.
- `README.md` contains user-facing installation and usage documentation.
- `tests/` contains Python unit tests and fresh-tmux-server integration coverage.

There is no compilation step or third-party package manifest. Runtime state is
stored in temporary JSON files.

## Build, Test, and Development Commands

Run these from the repository root:

```sh
bash -n tmux-remote-sessions.tmux
python3 -m unittest discover -s tests -p 'test_*.py'
shellcheck tmux-remote-sessions.tmux
tmux run-shell "$PWD/tmux-remote-sessions.tmux"
```

The syntax and unit-test commands should pass before review. The final command
runs the plugin entrypoint in the current tmux server, so use a disposable
server.

## Coding Style & Naming Conventions

Use two-space indentation in Bash and four-space indentation in Python. Keep
the generator standard-library-only, preserve executable bits, and use small
pure functions for parsing, scope classification, and tmux quoting.
Changes to forwarding levels should update the command sets, tests, and README
title-marker documentation together.

## Testing Guidelines

The test suite uses Python's `unittest` and disposable tmux servers. Manually
verify plain SSH (`TRS:shell`) stays local, each `TRS:` level forwards only its
scope, `prefix+s` stays local, and `prefix+r` cycles the remote title. Reload
should restore bindings without tracking state.

## Commit & Pull Request Guidelines

History uses short, descriptive subjects, generally in imperative form (for
example, `Better backslash support`); no strict conventional-commit prefix is
established. Keep commits focused. Pull requests should explain the behavior
change, list syntax/static or manual checks performed, note relevant tmux/OS
compatibility, and update `README.md` when user-visible behavior changes.

## Runtime and Configuration Notes

The plugin rewrites tmux prefix bindings and executes shell scripts in the
user's tmux environment. `TRS:pane`, `TRS:window`, and `TRS:session` title
markers select forwarding scope; `prefix+s` must remain local and `prefix+r`
must send the remote cycle key only for recognized titles. Review changes
involving command matching or quoting carefully, and do not commit generated
binding snapshots or temporary files.
