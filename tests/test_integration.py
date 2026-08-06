import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate_bindings as generator


PLUGIN_FILES = (
    "generate_bindings.py",
    "tmux-remote-sessions.tmux",
)


def tmux_environment():
    environment = os.environ.copy()
    environment.pop("TMUX", None)
    return environment


def run_tmux(socket_path, *arguments):
    return subprocess.run(
        ["tmux", "-S", str(socket_path), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=tmux_environment(),
    )


def start_server(socket_path):
    run_tmux(socket_path, "-f", "/dev/null", "new-session", "-d", "-s", "baseline")


def list_bindings(socket_path):
    format_string = generator.SEPARATOR.join(
        ("#{key_table}", "#{key_string}", "#{key_repeat}", "#{key_note}", "#{key_command}")
    )
    result = run_tmux(socket_path, "list-keys", "-T", "prefix", "-F", format_string)
    return {binding.key: binding for binding in generator.parse_bindings(result.stdout)}


def copy_plugin(destination):
    for filename in PLUGIN_FILES:
        shutil.copy2(ROOT / filename, destination / filename)


def remove_state(state_file):
    path = Path(state_file)
    if path.exists():
        path.unlink()
    if path.parent.name.startswith("tmux-remote-sessions."):
        try:
            path.parent.rmdir()
        except OSError:
            pass


@unittest.skipUnless(shutil.which("tmux"), "integration tests require tmux")
class PluginIntegrationTests(unittest.TestCase):
    def test_fresh_install_sets_state_and_current_local_bindings(self):
        with tempfile.TemporaryDirectory(prefix="tmux-remote-sessions-install-") as directory:
            directory_path = Path(directory)
            plugin_directory = directory_path / "plugin"
            plugin_directory.mkdir()
            socket_path = directory_path / "tmux.sock"
            start_server(socket_path)
            self.addCleanup(self.kill_server, socket_path)
            copy_plugin(plugin_directory)

            run_tmux(socket_path, "run-shell", str(plugin_directory / "tmux-remote-sessions.tmux"))

            state_file = run_tmux(
                socket_path,
                "show-option",
                "-gqv",
                "@tmux-remote-sessions-state-file",
            ).stdout.strip()
            self.addCleanup(remove_state, state_file)
            self.assertTrue(state_file)
            self.assertTrue(Path(state_file).is_file())
            self.assertEqual(
                run_tmux(
                    socket_path,
                    "show-option",
                    "-gqv",
                    "@tmux-remote-sessions-installed",
                ).stdout.strip(),
                "true",
            )

            bindings = list_bindings(socket_path)
            self.assertIn("TRS:pane*", bindings["r"].command)
            self.assertIn("send-prefix; send-keys R", bindings["r"].command)
            self.assertNotIn("send-prefix \\;", bindings["r"].command)
            self.assertNotIn("if-shell", bindings["s"].command)

    def test_reload_restores_and_replaces_python_state(self):
        with tempfile.TemporaryDirectory(prefix="tmux-remote-sessions-reload-") as directory:
            directory_path = Path(directory)
            plugin_directory = directory_path / "plugin"
            plugin_directory.mkdir()
            socket_path = directory_path / "tmux.sock"
            start_server(socket_path)
            self.addCleanup(self.kill_server, socket_path)
            copy_plugin(plugin_directory)

            entrypoint = str(plugin_directory / "tmux-remote-sessions.tmux")
            run_tmux(socket_path, "run-shell", entrypoint)
            first_state = Path(
                run_tmux(
                    socket_path,
                    "show-option",
                    "-gqv",
                    "@tmux-remote-sessions-state-file",
                ).stdout.strip()
            )

            run_tmux(socket_path, "run-shell", entrypoint)
            second_state = Path(
                run_tmux(
                    socket_path,
                    "show-option",
                    "-gqv",
                    "@tmux-remote-sessions-state-file",
                ).stdout.strip()
            )
            self.addCleanup(remove_state, second_state)

            self.assertNotEqual(first_state, second_state)
            self.assertFalse(first_state.exists())
            self.assertTrue(second_state.is_file())
            self.assertIn("send-prefix; send-keys R", list_bindings(socket_path)["r"].command)

    def test_title_markers_select_the_expected_forwarding_scope(self):
        with tempfile.TemporaryDirectory(prefix="tmux-remote-sessions-title-") as directory:
            socket_path = Path(directory) / "title.sock"
            start_server(socket_path)
            self.addCleanup(self.kill_server, socket_path)

            expected = {
                "TRS:pane:test": {"pane": True, "window": False, "session": False},
                "TRS:window:test": {"pane": True, "window": True, "session": False},
                "TRS:session:test": {"pane": True, "window": True, "session": True},
                "TRS:shell:test": {"pane": False, "window": False, "session": False},
            }
            for title, levels in expected.items():
                run_tmux(socket_path, "select-pane", "-T", title)
                for name, should_match in levels.items():
                    level = generator.BindingLevel[name.upper()]
                    actual = run_tmux(
                        socket_path,
                        "display-message",
                        "-p",
                        generator.title_condition(level),
                    ).stdout.strip()
                    with self.subTest(title=title, level=name):
                        self.assertEqual(actual, "1" if should_match else "0")

    @staticmethod
    def kill_server(socket_path):
        subprocess.run(
            ["tmux", "-S", str(socket_path), "kill-server"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=tmux_environment(),
        )


if __name__ == "__main__":
    unittest.main()
