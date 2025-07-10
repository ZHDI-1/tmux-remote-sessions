#!/usr/bin/env bash
set -e

# ...
# Applies remote tmux key bindings
# bind-key    -T prefix       PPage             copy-mode -u
# bind-key -r -T prefix       Up                select-pane -U

SCRIPT_DIR=$(cd $(dirname $0) && pwd)
source $SCRIPT_DIR/escape-util

if [ $# -ne 0 ]; then
  echo "Usage $0"
  exit 1
fi

declare -a FORWARD_MODE_WHITELIST=("prefix")

declare -a FORWARD_COMMAND_WHITELIST=("break-pane"
                                      "choose-buffer"
                                      "choose-tree -Zw"
                                      "clock-mode"
                                      "copy-mode"
                                      "delete-buffer"
                                      "display-message"
                                      "display-panes"
                                      "find-window" #pin
                                      "kill-pane" #pin
                                      "kill-window" #pin
                                      "last-pane"
                                      "last-window"
                                      "list-buffers"
                                      "move-window" #pin
                                      "new-window"
                                      "next-layout"
                                      "paste-buffer"
                                      "rename-window" #pin
                                      "resize-pane"
                                      "rotate-window"
                                      "select-layout"
                                      "select-pane"
                                      "select-window" #pin
                                      "split-window"
                                      "swap-pane"
                                      "previous-window"
                                      "next-window")


INPUT_FILE="$SCRIPT_DIR/original_bindings.txt"
TMP_FILE="$SCRIPT_DIR/tmpfile"
TRIGGER_COMMAND_FILE="$SCRIPT_DIR/trigger_file.sh"

tmux list-keys -T prefix > $INPUT_FILE

rm -f $TMP_FILE
rm -f $TRIGGER_COMMAND_FILE

bind_command_regexp="^bind-key +((-r) +)?-T ([^ ]+) +([^ ]+) +(.+)$"

while read -r line
do
  if [[ $line =~ $bind_command_regexp ]]; then
    bind_flags="${BASH_REMATCH[2]}"
    bind_key_table="${BASH_REMATCH[3]}"
    bind_key="${BASH_REMATCH[4]}"
    bind_command="${BASH_REMATCH[5]}"

    # A few key names need special quoting or escaping
    if [[ $bind_key == ";" || $bind_key == '\;' ]]; then
        send_key="';'"
        bind_key='\;'
        key_name="SemiColon"
    elif [[ $bind_key == "#" || $bind_key == '\#' ]]; then
        send_key="'#'"
        bind_key="'#'"
        key_name="Hash"
    elif [[ $bind_key == "$" || $bind_key == '\$' ]]; then
        bind_key="'$'"
        send_key="'$'"
        key_name="Dollar"
    elif [[ $bind_key == "'" || $bind_key == "\\'" ]]; then
        send_key="\\'"
        bind_key="\"'\""
        key_name="SingleQuote"
    elif [[ $bind_key == "\\\"" ]]; then
        bind_key="\\\""
        send_key="'\\\"'"
        key_name="DoubleQuote"
    elif [[ $bind_key == "~" ]]; then
        bind_key="'~'"
        send_key="'~'"
        key_name="Tilde"
    elif [[ $bind_key == "&" ]]; then
        bind_key="&"
        send_key="&"
        key_name="Ampersand"
    elif [[ $bind_key == '\\' ]]; then
        # unmodified bind_key
        send_key='\\\\'
        key_name="Backslash"
    elif [[ $bind_key == 'C-\\' ]]; then
        # unmodified bind_key
        send_key='C-\\\\'
        key_name="C-Backslash"
    elif [[ $bind_key == 'h' ]]; then
        send_key='Left'
    elif [[ $bind_key == 'l' ]]; then
        send_key='Right'
    elif [[ $bind_key == 'j' ]]; then
        send_key='Down'
    elif [[ $bind_key == 'k' ]]; then
        send_key='Up'
    elif [[ $bind_key == 'C-h' ]]; then
        send_key='C-Left'
    elif [[ $bind_key == 'C-l' ]]; then
        send_key='C-Right'
    elif [[ $bind_key == 'C-j' ]]; then
        send_key='C-Down'
    elif [[ $bind_key == 'C-k' ]]; then
        send_key='C-Up'
    elif [[ $bind_key == 'M-h' ]]; then
        send_key='M-Left'
    elif [[ $bind_key == 'M-l' ]]; then
        send_key='M-Right'
    elif [[ $bind_key == 'M-j' ]]; then
        send_key='M-Down'
    elif [[ $bind_key == 'M-k' ]]; then
        send_key='M-Up'
    elif [[ $bind_key == 'o' ]]; then
        send_key='l'
    else
        # unmodified bind_key
        send_key="$bind_key"
        key_name="$bind_key"
    fi

      for tmux_command in "${FORWARD_COMMAND_WHITELIST[@]}"; do
        if [[ "$bind_command" = *"$tmux_command"* && "$bind_command" != "display-menu"* ]]; then
          remote_keys="\"send-prefix ; send-keys $send_key\""
          remote_test="if-shell -F \"#{m:*remote,#{session_name}}\""
                bind_command=$(echo $bind_command | gsed 's/\"/\\\"/g')
                # echo $bind_command


            local_command="\"$bind_command\""
            bind_command="$remote_test $remote_keys $local_command"
                # echo $bind_command

            echo "unbind-key -T $bind_key_table $bind_key" >> $TMP_FILE
            echo "bind-key $bind_flags -T $bind_key_table $bind_key $bind_command" >> $TMP_FILE
          # fi
        fi
    done

  else
    echo "Regexp failed to parse bind-key line: '$line'"
    exit 1
  fi
done < "$INPUT_FILE"
tmux source-file $TMP_FILE
rm -f $TMP_FILE
