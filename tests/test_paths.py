"""F1-02 — dados fora do diretório do programa."""

import unittest
from pathlib import Path, PureWindowsPath

import app
from app.utils.paths import is_inside, resolve_paths
from app.utils.resources import asset_path


class PathsTest(unittest.TestCase):
    def test_windows_uses_programdata_and_localappdata(self):
        env = {"PROGRAMDATA": r"C:\ProgramData", "LOCALAPPDATA": r"C:\Users\ana\AppData\Local"}
        p = resolve_paths(env=env, platform="win32")
        self.assertEqual(PureWindowsPath(str(p.machine_root)),
                         PureWindowsPath(r"C:\ProgramData\VYONIX\DICOM Print"))
        self.assertEqual(PureWindowsPath(str(p.user_root)),
                         PureWindowsPath(r"C:\Users\ana\AppData\Local\VYONIX\DICOM Print"))

    def test_env_override_isolates_everything(self):
        p = resolve_paths(env={"VYONIX_HOME": "/tmp/vy"}, platform="win32")
        for d in p.all_dirs():
            self.assertTrue(is_inside(d, Path("/tmp/vy")), d)

    def test_explicit_override_wins_over_env(self):
        p = resolve_paths("/tmp/a", env={"VYONIX_HOME": "/tmp/b"}, platform="linux")
        self.assertTrue(is_inside(p.database_file, Path("/tmp/a")))

    def test_default_paths_are_not_inside_program_dir(self):
        program_dir = Path(app.__file__).resolve().parents[1]
        p = resolve_paths(env={}, platform="linux")
        for d in p.all_dirs():
            self.assertFalse(is_inside(d, program_dir), d)

    def test_service_and_ui_logs_are_separate(self):
        p = resolve_paths("/tmp/x")
        self.assertNotEqual(p.logs_dir_for("service"), p.logs_dir_for("ui"))

    def test_assets_exist_and_traversal_is_blocked(self):
        self.assertTrue(asset_path("vyonix_icon.svg").exists())
        self.assertTrue(asset_path("vyonix_logo.svg").exists())
        with self.assertRaises(ValueError):
            asset_path("../app/main.py")


if __name__ == "__main__":
    unittest.main()
