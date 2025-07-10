#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd $(dirname $0) && pwd)

cd $SCRIPT_DIR

apply-remote-session-bindings() {

  remote_binding_installed=$(tmux show-option -gqv @tmux-remote-sessions-installed)
  
  if [ -n "$remote_binding_installed" ]; then
    ./restore-tmux-keys.sh original_bindings.txt
    tmux set -g @tmux-remote-sessions-installed ''
    rm -f original_bindings.txt
  fi
  
  ./apply-remote-tmux-keys.sh
  tmux set -g @tmux-remote-sessions-installed 'true'
  tmux display-message "applied remote session key bindings"
  
  tmux bind-key -T prefix r run-shell $SCRIPT_DIR/toggle-remote-tmux.sh
}

# Apply remote binding after all the other plugins have finished
apply-remote-session-bindings
