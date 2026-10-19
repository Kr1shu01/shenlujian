"""Unattended native Windows recorder/editor acceptance check.

Loaded by --windows-smoke in both source and frozen builds. The GitHub runner's
own desktop is captured, never the user's desktop. Missing sound hardware is
reported explicitly; with an output device, decoded non-silent audio is required.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import traceback


def _process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}


class ApplicationSmoke:
    def __init__(self, window, report):
        from PyQt5.QtCore import QTimer
        self.window = window
        self.editor = window.editor
        self.recorder = window.recorder
        self.report = Path(report).resolve()
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.folder = self.report.parent / (self.report.stem + ' 录屏和音乐')
        self.folder.mkdir(exist_ok=True)
        self.checks = {}
        self.notes = []
        self.phase = 'starting'
        self.done = False
        self.started = time.monotonic()
        self.phase_started = self.started
        self.audio_buffers = 0
        self.audio_nonzero = False
        self.audio_probe_attached = False
        self.audio_position = 0
        self.decoder_buffers = 0
        self.decoder_nonzero = False
        self.decoder = None
        self.probe = None
        self.timer = QTimer(window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.editor.test_mode = True
        self.editor.export_finished.connect(self.exported)
        QTimer.singleShot(350, self.begin)

    def command(self, tool, arguments):
        from app.common.resources import media_tool
        from app.common.environment import clean_subprocess_environment
        program = media_tool(tool)
        if not program:
            raise RuntimeError(f'Cannot resolve {tool}')
        return subprocess.check_output([program, *arguments], stderr=subprocess.PIPE,
                                       env=clean_subprocess_environment(), timeout=45, **_process_options())

    def metadata(self, path):
        return json.loads(self.command('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))

    def begin(self):
        try:
            from PyQt5.QtCore import QLibraryInfo
            from PyQt5.QtMultimedia import QAudio, QAudioDeviceInfo
            from app.common.resources import media_tool
            if sys.platform != 'win32':
                raise RuntimeError('The Windows smoke test must run on Windows')
            self.checks['windows_capture_selected'] = bool(self.recorder.windows)
            self.checks['qt_multimedia_service_available'] = bool(self.editor.player.isAvailable())
            self.checks['ffmpeg_resolves'] = Path(media_tool('ffmpeg') or '').is_file()
            self.checks['ffprobe_resolves'] = Path(media_tool('ffprobe') or '').is_file()
            self.notes.append('Qt plugin directory: ' + QLibraryInfo.location(QLibraryInfo.PluginsPath))
            if getattr(sys, 'frozen', False):
                root = Path(sys.executable).parent.resolve()
                self.checks['bundled_ffmpeg_used'] = Path(media_tool('ffmpeg')).is_relative_to(root)
                self.checks['bundled_ffprobe_used'] = Path(media_tool('ffprobe')).is_relative_to(root)
            self.has_audio_device = bool(QAudioDeviceInfo.availableDevices(QAudio.AudioOutput))
            self.notes.append('Windows audio output device available: ' + str(self.has_audio_device))
            if not self.has_audio_device:
                self.notes.append('Audio-output smoke skipped: hosted runner has no speaker/audio device; music import and AAC export remain required.')
            self.song = self.folder / '独立音乐 track.mp3'
            self.command('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i',
                                   'sine=frequency=880:sample_rate=48000:duration=6',
                                   '-c:a', 'libmp3lame', str(self.song)])
            rec = self.recorder
            rec.self_test = True
            rec.finish_test = self.recorded
            rec.directory.setText(str(self.folder))
            rec.name.setText('Windows 录屏 smoke')
            rec.timestamp.setChecked(False)
            rec.minimize.setChecked(False)
            custom = next(i for i in range(rec.area.count()) if rec.area.itemData(i) is None)
            rec.area.setCurrentIndex(custom)
            screen = rec.capture_geometry.mappings[0].native
            rec.x.setValue(screen.x())
            rec.y.setValue(screen.y())
            rec.capture_w.setValue(min(320, screen.width()))
            rec.capture_h.setValue(min(240, screen.height()))
            native = next(i for i in range(rec.resolution.count()) if rec.resolution.itemData(i) == (0, 0))
            rec.resolution.setCurrentIndex(native)
            rec.fps.setValue(15)
            options = rec.collect_options()
            self.expected_size = options.video_size
            self.checks['gdi_command_selected'] = options.capture_backend == 'gdigrab'
            self.phase = 'recording'
            rec.start_recording()
        except Exception:
            self.finish(traceback.format_exc())

    def recorded(self, success):
        try:
            if not success:
                raise RuntimeError('GDI screen recording failed: ' + self.recorder.error_tail)
            self.recording = self.recorder.last_saved
            data = self.metadata(self.recording)
            video = next(stream for stream in data['streams'] if stream['codec_type'] == 'video')
            self.checks['gdi_recording_is_h264_mp4'] = video['codec_name'] == 'h264' and 'mp4' in data['format']['format_name']
            self.checks['gdi_recording_has_expected_size'] = (video['width'], video['height']) == tuple(self.expected_size)
            self.checks['gdi_recording_has_frames'] = int(video.get('nb_frames', 0)) >= 15
            self.checks['gdi_recording_has_expected_fps'] = video['avg_frame_rate'] == '15/1'
            self.checks['gdi_recording_finalized_duration'] = float(data['format']['duration']) > 1
            self.editor.add_to_project([str(self.recording), str(self.song)])
            self.phase = 'importing'
            self.phase_started = time.monotonic()
        except Exception:
            self.finish(traceback.format_exc())

    def audio_buffer(self, buffer, decoder=False):
        if decoder:
            self.decoder_buffers += 1
        else:
            self.audio_buffers += 1
        nonzero = False
        try:
            raw = buffer.constData().asstring(buffer.byteCount())
            # Decode signed PCM rather than treating unsigned 128 silence as sound.
            fmt = buffer.format()
            if fmt.sampleSize() == 16:
                samples = struct.unpack('<' + 'h' * (len(raw) // 2), raw)
                nonzero = any(abs(value) > 100 for value in samples)
            elif fmt.sampleSize() == 32 and fmt.sampleType() == fmt.Float:
                samples = struct.unpack('<' + 'f' * (len(raw) // 4), raw)
                nonzero = any(abs(value) > .003 for value in samples)
            else:
                silence = 128 if fmt.sampleSize() == 8 and fmt.sampleType() == fmt.UnSignedInt else 0
                nonzero = any(abs(value - silence) > 2 for value in raw)
            if decoder:
                self.decoder_nonzero |= nonzero
            else:
                self.audio_nonzero |= nonzero
        except Exception as error:
            self.notes.append('Cannot inspect audio buffer: ' + str(error))

    def tick(self):
        if self.done:
            return
        try:
            from PyQt5.QtMultimedia import QAudioProbe
            if time.monotonic() - self.started > 110:
                raise RuntimeError('Windows smoke timed out in phase ' + self.phase)
            ed = self.editor
            if self.phase == 'importing' and ed.project.clips and ed.project.audio_clips:
                self.checks['music_imports_as_independent_track'] = len(ed.project.clips) == 1 and len(ed.project.audio_clips) == 1
                ed.seek(0)
                entry = ed.audio_preview.players.get(ed.project.audio_clips[0].uid)
                if entry is None:
                    return
                self.audio_player = entry['player']
                self.checks['music_multimedia_service_available'] = bool(self.audio_player.isAvailable())
                self.probe = QAudioProbe(self.window)
                self.probe.audioBufferProbed.connect(self.audio_buffer)
                self.audio_probe_attached = self.probe.setSource(self.audio_player)
                ed.toggle_play()
                self.phase = 'previewing'
                self.phase_started = time.monotonic()
            elif self.phase == 'previewing':
                self.audio_position = max(self.audio_position, self.audio_player.position())
                enough_time = time.monotonic() - self.phase_started > 2.5
                if not enough_time:
                    return
                self.checks['video_preview_decodes_frames'] = ed.surface.frame_count > 0
                self.checks['preview_timeline_advances'] = ed.current_frame >= 15
                if self.has_audio_device:
                    self.checks['music_audio_probe_supported'] = bool(self.audio_probe_attached)
                    self.checks['music_preview_decodes_non_silent_buffers'] = self.audio_buffers > 0 and self.audio_nonzero
                    self.checks['music_preview_advances'] = self.audio_position > 500
                    if self.audio_player.error():
                        self.notes.append('Music player error: ' + self.audio_player.errorString())
                ed.seek(10)
                self.phase = 'seek-preview'
                self.phase_started = time.monotonic()
            elif self.phase == 'seek-preview' and time.monotonic() - self.phase_started > .7:
                self.checks['preview_seek_updates_timeline'] = ed.current_frame == 10 and not ed.wanted_play
                ed.seek(0)
                ed.output_directory.setText(str(self.folder))
                ed.output_name.setText('Windows 混音成片')
                ed.output_name_custom = True
                self.window.grab().save(str(self.report.with_suffix('.png')))
                self.phase = 'exporting'
                ed.start_export()
                if not ed.busy:
                    raise RuntimeError('Mixed-project export failed to start: ' + ed.logs.toPlainText())
        except Exception:
            self.finish(traceback.format_exc())

    def exported(self, success, path):
        if self.done or self.phase != 'exporting':
            return
        try:
            if not success:
                raise RuntimeError('Mix export failed: ' + self.editor.logs.toPlainText())
            data = self.metadata(path)
            streams = data['streams']
            self.checks['export_contains_h264_video'] = any(s['codec_type'] == 'video' and s['codec_name'] == 'h264' for s in streams)
            self.checks['export_contains_aac_music'] = any(s['codec_type'] == 'audio' and s['codec_name'] == 'aac' for s in streams)
            self.checks['export_preserves_music_tail'] = 5.8 < float(data['format']['duration']) < 6.3
            raw = self.command('ffmpeg', ['-v', 'error', '-i', path, '-ss', '0.5', '-t', '0.2',
                                          '-vn', '-ac', '1', '-ar', '48000', '-f', 's16le', 'pipe:1'])
            samples = struct.unpack('<' + 'h' * (len(raw) // 2), raw)
            self.checks['export_music_is_not_silent'] = bool(samples) and max(abs(value) for value in samples) > 100
            # Media Foundation audio decoding has no speaker dependency. This
            # remains mandatory even when the runner cannot render sound.
            from PyQt5.QtMultimedia import QAudioDecoder
            self.decoder = QAudioDecoder(self.window)
            self.decoder.bufferReady.connect(self.decoder_buffer)
            self.decoder.finished.connect(self.decoded)
            self.decoder.error.connect(self.decoder_error)
            self.decoder.setSourceFilename(str(self.song))
            self.phase = 'decoding-music'
            self.decoder.start()
        except Exception:
            self.finish(traceback.format_exc())

    def decoder_buffer(self):
        try:
            self.audio_buffer(self.decoder.read(), decoder=True)
        except Exception:
            self.finish(traceback.format_exc())

    def decoded(self):
        if self.done:
            return
        self.checks['qt_decoder_reads_non_silent_music_without_speaker'] = self.decoder_buffers > 0 and self.decoder_nonzero
        self.finish()

    def decoder_error(self, code):
        if code:
            self.finish('Qt audio decoder failed: ' + self.decoder.errorString())

    def finish(self, error=''):
        if self.done:
            return
        from PyQt5.QtCore import QProcess
        from PyQt5.QtWidgets import QApplication
        self.done = True
        self.timer.stop()
        if self.recorder.process.state() != QProcess.NotRunning:
            self.recorder.process.kill()
            self.recorder.process.waitForFinished(5000)
        if self.decoder is not None:
            self.decoder.stop()
        self.editor.shutdown_preview()
        self.window.hotkeys.close()
        passed = not error and bool(self.checks) and all(self.checks.values())
        result = {'passed': passed, 'frozen': bool(getattr(sys, 'frozen', False)),
                  'checks': self.checks, 'notes': self.notes,
                  'audio_buffers': self.audio_buffers, 'decoder_buffers': self.decoder_buffers, 'error': error}
        self.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        QApplication.instance().exit(0 if passed else 1)


def run_smoke(command, report, timeout=145):
    report = Path(report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([*command, '--windows-smoke', str(report)], timeout=timeout, **_process_options())
    if not report.is_file():
        raise RuntimeError(f'Application did not write {report}; exit code {process.returncode}')
    result = json.loads(report.read_text(encoding='utf-8'))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if process.returncode or not result.get('passed'):
        raise RuntimeError('Windows application acceptance check failed')
    if os.environ.get('GITHUB_ACTIONS'):
        details = json.dumps(result, ensure_ascii=True).replace('%', '%25')
        print('::notice title=Windows application smoke passed::' + details, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Run on Windows')
    if args.executable:
        executable = args.executable.resolve()
        # A stock Windows PATH proves packaged operation without installed Python/FFmpeg.
        environment_path = os.environ.get('PATH')
        os.environ['PATH'] = os.pathsep.join([str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']])
        try:
            run_smoke([str(executable)], args.report)
        finally:
            if environment_path is not None:
                os.environ['PATH'] = environment_path
    else:
        root = Path(__file__).resolve().parents[1]
        run_smoke([sys.executable, str(root / 'shenlujian.py')], args.report)


if __name__ == '__main__':
    main()
