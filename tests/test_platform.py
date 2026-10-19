"""Packaged media tools, subprocess isolation and Windows DPI startup."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.common import environment, resources


class PackagedMediaToolTests(unittest.TestCase):
    def test_windows_install_with_spaces_and_unicode_uses_own_tools_before_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / '神录剪 install with spaces'
            tools = root / 'ffmpeg' / 'bin'
            tools.mkdir(parents=True)
            for name in ('ffmpeg', 'ffprobe'):
                (tools / (name + '.exe')).touch()
            internal = root / '_internal'
            internal.mkdir()
            with patch.object(resources.sys, 'platform', 'win32'), \
                 patch.object(resources.sys, 'frozen', True, create=True), \
                 patch.object(resources.sys, 'executable', str(root / 'shenlujian.exe')), \
                 patch.object(resources, 'RESOURCE_DIR', internal), \
                 patch.object(resources.shutil, 'which', return_value='unrelated.exe') as which:
                self.assertEqual(resources.media_tool('ffmpeg'), str(tools / 'ffmpeg.exe'))
                self.assertEqual(resources.media_tool('ffprobe'), str(tools / 'ffprobe.exe'))
                which.assert_not_called()

    def test_internal_tools_are_supported_and_working_directory_is_not_searched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bin').mkdir()
            (root / 'bin' / 'ffmpeg').touch()
            with patch.object(resources, 'RESOURCE_DIR', root), \
                 patch.object(resources.sys, 'platform', 'linux'), \
                 patch.object(resources.sys, 'frozen', False, create=True):
                self.assertEqual(resources.media_tool('ffmpeg'), str(root / 'bin' / 'ffmpeg'))
                with patch.object(resources.shutil, 'which', return_value='/usr/bin/ffprobe'):
                    self.assertEqual(resources.media_tool('ffprobe'), '/usr/bin/ffprobe')
                with self.assertRaises(ValueError):
                    resources.media_tool('../unrelated')


class ChildEnvironmentTests(unittest.TestCase):
    def test_frozen_subprocess_uses_original_library_path_without_changing_app(self):
        values = {'LD_LIBRARY_PATH': '/temporary/app', 'LD_LIBRARY_PATH_ORIG': '/user/lib', 'PATH': '/bin'}
        with patch.dict(os.environ, values, clear=True), \
             patch.object(environment.sys, 'frozen', True, create=True):
            result = environment.clean_subprocess_environment()
            self.assertEqual(result['LD_LIBRARY_PATH'], '/user/lib')
            self.assertEqual(os.environ['LD_LIBRARY_PATH'], '/temporary/app')
            self.assertEqual(environment.clean_child_environment().value('LD_LIBRARY_PATH'), '/user/lib')

    def test_unset_original_library_path_does_not_leak_into_external_ffmpeg(self):
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/temporary/app'}, clear=True), \
             patch.object(environment.sys, 'frozen', True, create=True):
            self.assertNotIn('LD_LIBRARY_PATH', environment.clean_subprocess_environment())

    def test_windows_subprocess_is_console_free_and_linux_flags_are_unchanged(self):
        with patch.object(environment.sys, 'platform', 'win32'):
            self.assertEqual(environment.subprocess_options(), {'creationflags': 0x08000000})
        with patch.object(environment.sys, 'platform', 'linux'):
            self.assertEqual(environment.subprocess_options(), {})

    def test_windows_dpi_request_is_per_monitor_v2_and_linux_never_loads_win32(self):
        user32 = MagicMock()
        user32.SetProcessDpiAwarenessContext.return_value = 1
        with patch.object(environment.sys, 'platform', 'win32'), \
             patch.object(environment.ctypes, 'WinDLL', return_value=user32, create=True):
            environment.configure_windows_dpi_awareness()
        self.assertEqual(user32.SetProcessDpiAwarenessContext.call_args.args[0].value,
                         environment.ctypes.c_void_p(-4).value)
        with patch.object(environment.sys, 'platform', 'linux'), \
             patch.object(environment.ctypes, 'WinDLL', create=True) as load:
            environment.configure_windows_dpi_awareness()
            load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
