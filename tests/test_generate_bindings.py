import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate_bindings as generator


class BindingGeneratorTests(unittest.TestCase):
    def binding(self, key="%", command="split-window -h", repeat=False, note=""):
        return generator.Binding("prefix", key, repeat, note, command)

    def test_command_levels_include_nested_commands(self):
        self.assertEqual(
            generator.command_level("split-window -h"), generator.BindingLevel.PANE
        )
        self.assertEqual(
            generator.command_level("next-window"), generator.BindingLevel.WINDOW
        )
        self.assertEqual(
            generator.command_level("choose-tree -Zs"), generator.BindingLevel.SESSION
        )
        self.assertEqual(
            generator.command_level(
                'command-prompt -T target { select-window -t ":%%" }'
            ),
            generator.BindingLevel.WINDOW,
        )
        self.assertEqual(
            generator.command_level(
                'confirm-before -p "kill-window #W? (y/n)" kill-window'
            ),
            generator.BindingLevel.WINDOW,
        )

    def test_quoted_command_text_is_not_classified(self):
        self.assertIsNone(
            generator.command_level('run-shell "split-window is disabled"')
        )
        self.assertIsNone(
            generator.command_level(
                'display-menu "Split" s { split-window }'
            )
        )

    def test_prefix_s_is_always_local(self):
        output = generator.render_apply(
            [self.binding(key="s", command="choose-tree -Zs")]
        )
        self.assertEqual(output, "")

    def test_title_conditions_are_ordered_by_scope(self):
        pane = generator.title_condition(generator.BindingLevel.PANE)
        window = generator.title_condition(generator.BindingLevel.WINDOW)
        session = generator.title_condition(generator.BindingLevel.SESSION)

        self.assertIn("TRS:pane*", pane)
        self.assertIn("TRS:window*", pane)
        self.assertIn("TRS:session*", pane)
        self.assertNotIn("TRS:pane*", window)
        self.assertIn("TRS:window*", window)
        self.assertIn("TRS:session*", window)
        self.assertNotIn("TRS:window*", session)
        self.assertIn("TRS:session*", session)
        self.assertNotIn("@tmux-remote-sessions-level", pane)

    def test_special_keys_are_quoted_in_generated_config(self):
        keys = [';', '#', '$', "'", '"', '~', '&', '\\', 'C-\\']
        output = generator.render_apply(
            [self.binding(key=key) for key in keys]
        )

        for key in keys:
            self.assertIn("unbind-key -T \"prefix\"", output)
            self.assertIn(generator.tmux_quote(key), output)

    def test_state_round_trip_is_json(self):
        bindings = [self.binding(key="%", repeat=True, note="test note")]
        local_bindings = [self.binding(key="r", command="refresh-client")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            generator.write_state(str(path), bindings, local_bindings)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["version"], generator.STATE_VERSION)
            state = generator.read_state(str(path))
            self.assertEqual(state.bindings, bindings)
            self.assertEqual(state.local_bindings, local_bindings)

    def test_restore_preserves_repeat_and_note(self):
        output = generator.render_restore(
            [self.binding(key="%", repeat=True, note="test note")]
        )
        self.assertIn('bind-key -r -T "prefix" -N "test note" "%"', output)
        self.assertIn('"split-window -h"', output)


if __name__ == "__main__":
    unittest.main()
