"""Windows capture contracts, runnable on Linux with native APIs mocked."""
import ctypes
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import QByteArray, QRect

from app.common.hotkeys import GlobalHotkeys, WindowsHotkeyFilter, WindowsMessage
from app.recording.commands import RecordingOptions, ffmpeg_arguments, output_path
from app.recording.geometry import CaptureGeometry, screen_choices, windows_native_rectangles


class WindowsRecordingTests(unittest.TestCase):
    def test_gdigrab_uses_native_negative_offsets_and_no_x11_display(self):
        options = RecordingOptions('', -2560, -180, 2560, 1440,
                                   fps=60, cursor=False, capture_backend='gdigrab')
        target = Path('录屏 with spaces.mp4')
        arguments = ffmpeg_arguments(options, target)
        self.assertEqual(arguments[arguments.index('-f') + 1], 'gdigrab')
        self.assertEqual(arguments[arguments.index('-i') + 1], 'desktop')
        self.assertEqual(arguments[arguments.index('-offset_x') + 1], '-2560')
        self.assertEqual(arguments[arguments.index('-offset_y') + 1], '-180')
        self.assertEqual(arguments[arguments.index('-video_size') + 1], '2560x1440')
        self.assertEqual(arguments[arguments.index('-draw_mouse') + 1], '0')
        self.assertEqual(arguments[-1], str(target))
        self.assertNotIn('-nostdin', arguments)  # q + newline must finalize MP4.
        self.assertNotIn('x11grab', arguments)

    def test_unknown_capture_backend_cannot_launch(self):
        with self.assertRaises(ValueError):
            ffmpeg_arguments(RecordingOptions('', 0, 0, 100, 100, capture_backend='other'), Path('a.mp4'))

    def test_windows_reserved_output_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch('app.recording.commands.sys.platform', 'win32'):
            for name in ['CON', 'con.txt', 'LPT1', 'COM9.any', 'a:b', 'a?', 'a|b', 'ending.']:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    output_path(folder, name, False)
            self.assertEqual(output_path(folder, '七月剪辑', False).name, '七月剪辑.mp4')

    def test_windows_monitor_api_matches_names_to_physical_bounds(self):
        user32 = MagicMock()
        rectangles = [(-2560, -180, 0, 1260), (0, 0, 3840, 2160)]

        def monitor_info(handle, pointer):
            info = pointer._obj
            left, top, right, bottom = rectangles[handle - 1]
            info.rcMonitor.left, info.rcMonitor.top = left, top
            info.rcMonitor.right, info.rcMonitor.bottom = right, bottom
            info.szDevice = '\\\\.\\DISPLAY' + str(handle)
            self.assertEqual(info.cbSize, ctypes.sizeof(info))
            return 1

        def enumerate_monitors(hdc, clip, callback, data):
            callback(1, None, None, data)
            callback(2, None, None, data)
            return 1

        user32.GetMonitorInfoW.side_effect = monitor_info
        user32.EnumDisplayMonitors.side_effect = enumerate_monitors
        native = windows_native_rectangles(user32)
        self.assertEqual(native['\\\\.\\display1'], QRect(-2560, -180, 2560, 1440))
        # Qt positions remain desktop-relative; dimensions reflect each DPR.
        screens = [
            SimpleNamespace(name=lambda: '\\\\.\\DISPLAY1', geometry=lambda: QRect(-2560, -180, 2048, 1152)),
            SimpleNamespace(name=lambda: '\\\\.\\DISPLAY2', geometry=lambda: QRect(0, 0, 1920, 1080)),
        ]
        with patch('app.recording.geometry.sys.platform', 'win32'), patch('app.recording.geometry.windows_native_rectangles', return_value=native):
            model = CaptureGeometry.detect(screens)
        self.assertEqual(model.root, QRect(-2560, -180, 6400, 2340))
        self.assertEqual(model.to_native(QRect(-2560, -180, 2048, 1152)), QRect(-2560, -180, 2560, 1440))
        self.assertEqual(model.to_native(QRect(100, 50, 400, 200)), QRect(200, 100, 800, 400))
        self.assertEqual(screen_choices(model, '\\\\.\\DISPLAY2')[0][1], QRect(0, 0, 3840, 2160))

    def test_monitor_enumeration_error_is_reported(self):
        user32 = MagicMock()
        user32.EnumDisplayMonitors.return_value = 0
        with self.assertRaises(OSError):
            windows_native_rectangles(user32)

    def test_monitor_api_failure_falls_back_to_each_qt_screen_dpr(self):
        screens = [SimpleNamespace(name=lambda: 'secondary', geometry=lambda: QRect(-1920, -120, 1536, 864), devicePixelRatio=lambda: 1.25)]
        with patch('app.recording.geometry.sys.platform', 'win32'), patch('app.recording.geometry.windows_native_rectangles', side_effect=OSError('unavailable')):
            model = CaptureGeometry.detect(screens)
        self.assertEqual(model.root, QRect(-1920, -120, 1920, 1080))
        self.assertEqual(model.to_native(QRect(-1920, -120, 1536, 864)), model.root)


class WindowsHotkeyTests(unittest.TestCase):
    def test_registration_conflict_falls_back_and_cleanup_unregisters_only_owned_key(self):
        user32 = MagicMock()
        user32.RegisterHotKey.side_effect = [1, 0]
        application = MagicMock()
        with patch('app.common.hotkeys.sys.platform', 'win32'), patch('app.common.hotkeys.C.WinDLL', return_value=user32, create=True), patch('app.common.hotkeys.QCoreApplication.instance', return_value=application):
            hotkeys = GlobalHotkeys(None, {'F9': lambda: None, 'F10': lambda: None})
        self.assertEqual(hotkeys.registered, {'F9'})
        self.assertIn('F10', hotkeys.error)
        user32.RegisterHotKey.assert_any_call(None, 0x5300, 0x4000, 0x78)
        self.assertEqual(application.installNativeEventFilter.call_count, 1)
        hotkeys.close()
        hotkeys.close()
        user32.UnregisterHotKey.assert_called_once_with(None, 0x5300)
        self.assertEqual(application.removeNativeEventFilter.call_count, 1)
        self.assertEqual(hotkeys.registered, set())

    def test_hotkey_dispatch_uses_registered_identifier_and_gui_event_loop(self):
        callback = MagicMock()
        native_filter = WindowsHotkeyFilter({0x5300: callback})
        message = WindowsMessage(message=0x0312, wParam=0x5300)
        with patch('app.common.hotkeys.QTimer.singleShot') as queued:
            self.assertEqual(native_filter.nativeEventFilter(QByteArray(b'windows_dispatcher_MSG'), ctypes.addressof(message)), (True, 0))
            self.assertEqual(queued.call_args.args[0], 0)
            deferred = queued.call_args.args[1]
        callback.assert_not_called()
        deferred()
        callback.assert_called_once_with()
        native_filter.callbacks.clear()
        deferred()  # A queued native event cannot call a widget after close().
        callback.assert_called_once_with()
        message.wParam = 99
        self.assertEqual(native_filter.nativeEventFilter(QByteArray(b'windows_dispatcher_MSG'), ctypes.addressof(message)), (False, 0))
        self.assertEqual(native_filter.nativeEventFilter(QByteArray(b'xcb_generic_event_t'), 0), (False, 0))

    def test_missing_windows_api_keeps_in_window_fallback_available(self):
        with patch('app.common.hotkeys.sys.platform', 'win32'), patch('app.common.hotkeys.C.WinDLL', side_effect=OSError('unavailable'), create=True), patch('app.common.hotkeys.QCoreApplication.instance', return_value=MagicMock()):
            hotkeys = GlobalHotkeys(None, {'F9': lambda: None, 'F10': lambda: None})
        self.assertEqual(hotkeys.registered, set())
        self.assertIn('仅在窗口内生效', hotkeys.error)


if __name__ == '__main__':
    unittest.main()
