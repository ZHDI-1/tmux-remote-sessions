import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
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
            self.assertIn("send-prefix; send-keys C-r", bindings["R"].command)
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

    def test_optional_navigation_and_current_path_behavior(self):
        with tempfile.TemporaryDirectory(prefix="tmux-remote-sessions-options-") as directory:
            directory_path = Path(directory)
            plugin_directory = directory_path / "plugin"
            plugin_directory.mkdir()
            socket_path = directory_path / "tmux.sock"
            start_server(socket_path)
            self.addCleanup(self.kill_server, socket_path)
            copy_plugin(plugin_directory)

            run_tmux(
                socket_path,
                "bind-key",
                "-r",
                "-T",
                "prefix",
                "h",
                "select-pane",
                "-L",
            )

            run_tmux(
                socket_path,
                "set-option",
                "-g",
                generator.VIM_NAVIGATION_OPTION,
                "off",
            )
            run_tmux(
                socket_path,
                "set-option",
                "-g",
                generator.PRESERVE_CURRENT_PATH_OPTION,
                "on",
            )
            run_tmux(socket_path, "run-shell", str(plugin_directory / "tmux-remote-sessions.tmux"))

            state_file = run_tmux(
                socket_path,
                "show-option",
                "-gqv",
                "@tmux-remote-sessions-state-file",
            ).stdout.strip()
            self.addCleanup(remove_state, state_file)

            bindings = list_bindings(socket_path)
            self.assertIn('send-keys \\"h\\"', bindings["h"].command)
            self.assertNotIn('send-keys \\"Left\\"', bindings["h"].command)
            self.assertIn(
                'split-window -c \\"#{pane_current_path}\\"',
                bindings["%"].command,
            )

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


@unittest.skipUnless(shutil.which("tmux"), "integration tests require tmux")
class RemoteConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="trs-remote-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.remote = self.directory / "remote.sock"
        self.start_server(self.remote)
        self.source_remote_snippet("Remote configuration")

    def source_remote_snippet(self, heading):
        section = (ROOT / "README.md").read_text().split("### " + heading + "\n", 1)[1]
        snippet = section.split("```tmux\n", 1)[1].split("```", 1)[0]
        config = self.directory / "remote.conf"
        config.write_text(snippet)
        run_tmux(self.remote, "source-file", str(config))

    def start_server(self, socket):
        run_tmux(
            socket, "-f", "/dev/null", "new-session", "-d", "-s", "baseline",
            "-x", "120", "-y", "40", "-c", str(self.directory), "/bin/sh",
        )
        self.addCleanup(PluginIntegrationTests.kill_server, socket)
        run_tmux(socket, "set-option", "-g", "default-shell", "/bin/sh")

    def install(self, socket):
        run_tmux(socket, "run-shell", str(ROOT / "tmux-remote-sessions.tmux"))
        state = run_tmux(socket, "show-option", "-gqv", generator.STATE_FILE_OPTION).stdout.strip()
        self.addCleanup(remove_state, state)
        return Path(state)

    def press(self, socket, key):
        # Execute the stored binding in the active pane's context. On the outer
        # server this sends real prefix/key bytes to the attached inner client.
        config = self.directory / "press.conf"
        config.write_text(
            "if-shell -F 1 " + generator.tmux_quote(list_bindings(socket)[key].command) + "\n"
        )
        run_tmux(socket, "source-file", str(config))

    def wait_for(self, read, expected):
        deadline = time.monotonic() + 5
        while True:
            actual = read()
            if actual == expected:
                return
            if time.monotonic() >= deadline:
                self.assertEqual(actual, expected)
            time.sleep(0.02)

    def level(self):
        return run_tmux(self.remote, "display-message", "-p", "#{@trs-level}").stdout.strip()

    def pane_path(self, socket, target=None):
        arguments = ["display-message", "-p"]
        if target:
            arguments.extend(("-t", target))
        arguments.append("#{pane_current_path}")
        return run_tmux(socket, *arguments).stdout.strip()

    def test_remote_cycle_modes_and_session_return(self):
        for level in ("window", "pane", "window", "pane"):
            self.press(self.remote, "R")
            self.assertEqual(self.level(), level)

        for origin in ("pane", "window"):
            run_tmux(self.remote, "set-option", "@trs-level", origin)
            self.press(self.remote, "C-r")
            self.assertEqual(self.level(), "session")
            self.press(self.remote, "C-r")
            self.assertEqual(self.level(), origin)
        self.press(self.remote, "C-r")
        self.press(self.remote, "R")
        self.assertEqual(self.level(), "pane")

    def test_documented_three_level_cycle_and_session_return(self):
        self.source_remote_snippet("Three-level cycling")
        for key, level in (
            ("R", "window"), ("R", "session"), ("C-r", "window"),
            ("R", "session"), ("R", "pane"),
        ):
            self.press(self.remote, key)
            self.assertEqual(self.level(), level)

    def test_restore_removes_controls_that_were_originally_unbound(self):
        local = self.directory / "local.sock"
        self.start_server(local)
        original = list_bindings(local)
        state_file = self.install(local)
        state = generator.read_state(str(state_file))
        config = self.directory / "restore.conf"
        config.write_text(generator.render_restore(state.bindings, state.local_bindings, state.owned_keys))
        run_tmux(local, "source-file", str(config))
        self.assertEqual(list_bindings(local), original)

    def test_remote_path_is_evaluated_when_binding_runs(self):
        explicit = self.directory / "explicit path"
        explicit.mkdir()
        run_tmux(self.remote, "bind-key", "v", "new-window", "-c", str(explicit))
        original = list_bindings(self.remote)["v"]
        self.source_remote_snippet("Remote working directories")
        self.assertEqual(list_bindings(self.remote)["v"], original)

        changed = self.directory / "remote space ' quote $dollar ; semi"
        changed.mkdir()
        run_tmux(self.remote, "send-keys", "cd " + shlex.quote(str(changed)), "Enter")
        self.wait_for(lambda: self.pane_path(self.remote), str(changed.resolve()))
        for key in ("%", '"', "c"):
            with self.subTest(key=key):
                self.press(self.remote, key)
                self.wait_for(lambda: self.pane_path(self.remote), str(changed.resolve()))
        self.press(self.remote, "v")
        self.wait_for(lambda: self.pane_path(self.remote), str(explicit.resolve()))

    def test_local_reload_restores_control_keys_and_paths(self):
        local = self.directory / "local.sock"
        self.start_server(local)
        for key in ("r", "R"):
            run_tmux(local, "bind-key", "-r", "-N", "original " + key,
                     key, "display-message", "original " + key)
        original = list_bindings(local)
        run_tmux(local, "set-option", "-g", generator.PRESERVE_CURRENT_PATH_OPTION, "on")
        first_state = self.install(local)
        self.install(local)
        self.assertFalse(first_state.exists())

        run_tmux(local, "set-option", "-g", generator.PRESERVE_CURRENT_PATH_OPTION, "off")
        state = generator.read_state(str(self.install(local)))
        self.assertNotIn("pane_current_path", list_bindings(local)["%"].command)
        self.assertCountEqual(state.local_bindings, [original["r"], original["R"]])
        config = self.directory / "restore.conf"
        config.write_text(generator.render_restore(state.bindings, state.local_bindings, state.owned_keys))
        run_tmux(local, "source-file", str(config))
        self.assertEqual(list_bindings(local), original)

    def test_nested_forwarding_uses_remote_path_and_scope_controls(self):
        remote_path = self.directory / "remote working directory"
        remote_path.mkdir()
        run_tmux(self.remote, "send-keys", "cd " + shlex.quote(str(remote_path)), "Enter")
        self.wait_for(lambda: self.pane_path(self.remote), str(remote_path.resolve()))
        self.source_remote_snippet("Remote working directories")

        local = self.directory / "local.sock"
        self.start_server(local)
        run_tmux(local, "set-option", "-g", "allow-set-title", "on")
        run_tmux(local, "set-option", "-g", generator.PRESERVE_CURRENT_PATH_OPTION, "on")
        # Replace only this disposable pane's shell with a nested tmux client.
        attach = "exec env -u TMUX tmux -S {} attach-session -t baseline".format(
            shlex.quote(str(self.remote))
        )
        run_tmux(local, "send-keys", attach, "Enter")
        self.wait_for(
            lambda: run_tmux(local, "display-message", "-p", "#{pane_title}").stdout.strip(),
            "TRS:pane:remote",
        )
        self.install(local)
        self.press(local, "%")
        self.wait_for(
            lambda: len(run_tmux(self.remote, "list-panes").stdout.splitlines()), 2,
        )
        self.wait_for(lambda: self.pane_path(self.remote), str(remote_path.resolve()))
        self.assertEqual(len(run_tmux(local, "list-panes").stdout.splitlines()), 1)

        for key, level in (("r", "window"), ("R", "session"), ("R", "window"), ("r", "pane")):
            self.press(local, key)
            self.wait_for(self.level, level)
            self.wait_for(
                lambda: run_tmux(local, "display-message", "-p", "#{pane_title}").stdout.strip(),
                "TRS:" + level + ":remote",
            )
        self.press(local, "r")
        self.wait_for(self.level, "window")
        self.wait_for(
            lambda: run_tmux(local, "display-message", "-p", "#{pane_title}").stdout.strip(),
            "TRS:window:remote",
        )
        self.press(local, "c")
        self.wait_for(lambda: len(run_tmux(self.remote, "list-windows").stdout.splitlines()), 2)
        self.wait_for(lambda: self.pane_path(self.remote), str(remote_path.resolve()))
        self.assertNotIn("if-shell", list_bindings(local)["s"].command)
        self.assertEqual(
            run_tmux(self.remote, "show-option", "-gqv", generator.INSTALLED_OPTION).stdout.strip(),
            "",
        )

    def test_plain_shell_does_not_receive_control_keys(self):
        local = self.directory / "shell.sock"
        self.start_server(local)
        self.install(local)
        run_tmux(local, "select-pane", "-T", "TRS:shell:test")
        self.press(local, "r")
        self.press(local, "R")
        run_tmux(local, "send-keys", "printf 'plain-shell-ok\\n'", "Enter")
        self.wait_for(
            lambda: "plain-shell-ok" in run_tmux(local, "capture-pane", "-p").stdout.splitlines(),
            True,
        )


if __name__ == "__main__":
    unittest.main()
