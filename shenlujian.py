#!/usr/bin/env python3
"""神录剪 combines the existing recorder with a basic frame editor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QSplitter, QSystemTrayIcon, QVBoxLayout, QWidget, QShortcut
from recorder_ui import RecorderWindow, RESOURCE_DIR, STYLE
from editor_ui import EditorPanel
from global_hotkeys import GlobalHotkeys

APP_ID='shenlujian'
APP_NAME='神录剪'
DESCRIPTION='随手一录，轻松一剪。'
EXTRA_STYLE='''
QPushButton#export { background:#7ac7ae; color:#10241c; border:0; padding:12px 20px; font-weight:700; }
QPushButton#export:hover { background:#94dfc7; }
QPushButton#export:disabled { background:#324d45; color:#819e92; }
QListWidget { background:#101924; border:1px solid #314155; border-radius:6px; padding:4px; }
QListWidget::item:selected { background:#344d65; }
QProgressBar { background:#101924; border:1px solid #314155; border-radius:6px; text-align:center; height:18px; }
QProgressBar::chunk { background:#65bda0; border-radius:5px; }
QSplitter::handle { background:#34465b; width:5px; }
'''


class RecorderPanel(RecorderWindow):
    def __init__(self,host):
        self.host=host
        super().__init__()
        self.setWindowFlags(Qt.Widget)
        self.setMinimumSize(700,600)
        for label in self.findChildren(QLabel):
            if label.objectName()=='title':label.setText('录')
        if self.tray:self.tray.hide();self.tray.deleteLater();self.tray=None

    def showMinimized(self):self.host.showMinimized()
    def showNormal(self):self.host.showMaximized()
    def raise_(self):self.host.raise_()


class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(RESOURCE_DIR/'assets/shenlujian.svg')))
        self.setToolTip(DESCRIPTION)
        self.resize(1840,1080);self.setMinimumSize(1460,800)
        self.want_close=False
        QShortcut('F11',self,activated=self.toggle_fullscreen)
        QShortcut('Escape',self,activated=self.leave_fullscreen)
        central=QWidget();layout=QVBoxLayout(central);layout.setContentsMargins(12,8,12,0);layout.setSpacing(4)
        branding=QHBoxLayout();icon=QLabel();icon.setPixmap(self.windowIcon().pixmap(30,30));icon.setToolTip(DESCRIPTION)
        branding.addWidget(icon);name=QLabel(APP_NAME);name.setObjectName('section');name.setToolTip(DESCRIPTION)
        branding.addWidget(name);branding.addStretch();tagline=QLabel(DESCRIPTION);tagline.setObjectName('muted')
        branding.addWidget(tagline);layout.addLayout(branding)
        self.recorder=RecorderPanel(self);self.editor=EditorPanel()
        self.splitter=QSplitter(Qt.Horizontal);self.splitter.addWidget(self.recorder);self.splitter.addWidget(self.editor)
        self.splitter.setChildrenCollapsible(False);self.splitter.setSizes([760,1780]);layout.addWidget(self.splitter,1)
        self.setCentralWidget(central)
        self.hotkeys=GlobalHotkeys(self,{'F9':self.recorder.start_recording,'F10':self.recorder.stop_recording})
        for key,callback in [('F9',self.recorder.start_recording),('F10',self.recorder.stop_recording)]:
            if key not in self.hotkeys.registered:
                shortcut=QShortcut(key,self,activated=callback);shortcut.setAutoRepeat(False)
        if self.hotkeys.error:self.recorder.logs.append(self.hotkeys.error)
        self.editor.import_recording.clicked.connect(self.import_recording)
        self.recorder.process.finished.connect(self.recording_finished)
        self.editor.export_finished.connect(self.maybe_close)
        self.tray=None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray=QSystemTrayIcon(self.windowIcon(),self);self.tray.setToolTip(DESCRIPTION)
            self.tray.activated.connect(self.tray_clicked);self.tray.show()
        available=QApplication.primaryScreen().availableGeometry()
        if self.width()>available.width()-40 or self.height()>available.height()-60:
            self.resize(min(self.width(),available.width()-40),min(self.height(),available.height()-60))
        self.move(available.center().x()-self.width()//2,available.center().y()-self.height()//2)

    def toggle_fullscreen(self):
        if self.isFullScreen():self.showMaximized()
        else:self.showFullScreen()

    def leave_fullscreen(self):
        if self.isFullScreen():self.showMaximized()

    def recording_finished(self,*_):
        self.editor.import_recording.setEnabled(self.recorder.last_saved is not None)
        self.maybe_close()

    def import_recording(self):
        if self.recorder.last_saved:self.editor.load_video(self.recorder.last_saved)

    def tray_clicked(self,reason):
        if reason in (QSystemTrayIcon.Trigger,QSystemTrayIcon.DoubleClick):
            self.showMaximized();self.raise_();self.activateWindow()

    def maybe_close(self,*_):
        if self.want_close and self.recorder.state=='idle' and not self.editor.busy:QTimer.singleShot(0,self.close)

    def closeEvent(self,event):
        if self.recorder.state!='idle' or self.editor.busy:
            self.want_close=True
            if self.recorder.state=='starting':
                self.recorder.close_after_stop=True
                if self.recorder.wayland:self.recorder.stop_recording()
            if self.recorder.state=='recording':self.recorder.stop_recording()
            event.ignore();return
        self.recorder.save_settings();self.editor.shutdown_preview();self.hotkeys.close()
        if self.tray:self.tray.hide()
        event.accept()


class IntegrationCheck:
    def __init__(self,window,source,result):
        self.window=window;self.source=Path(source).resolve();self.result=Path(result).resolve()
        self.phase='loading';self.results={};self.done=False
        self.original_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        editor=window.editor;editor.test_mode=True;editor.player.setVolume(0)
        editor.video_loaded.connect(self.loaded);editor.export_finished.connect(self.exported)
        window.recorder.process.finished.connect(self.recorded)
        QTimer.singleShot(400,lambda:editor.load_video(self.source))
        QTimer.singleShot(40000,lambda:self.finish(False,'Integration test timed out'))

    def loaded(self):
        editor=self.window.editor
        if self.phase=='recorded-import':
            self.results['recording_import']=(editor.info.path==self.window.recorder.last_saved)
            self.finish(all(self.results.values()));return
        if self.phase!='loading':return
        self.phase='preview';editor.toggle_play()
        QTimer.singleShot(1500,self.edit_and_export)

    def edit_and_export(self):
        editor=self.window.editor
        self.results['video_preview']=editor.player.position()>300 and not editor.player.error() and editor.surface.frame_count>10
        editor.seek(1)
        QTimer.singleShot(150,self.check_first_frame)

    def check_first_frame(self):
        editor=self.window.editor
        self.results['frame_step']=editor.current_frame==1
        editor.seek(2)
        QTimer.singleShot(150,self.begin_export)

    def begin_export(self):
        editor=self.window.editor
        self.results['frame_step']=self.results['frame_step'] and editor.current_frame==2
        editor.project.delete_range(150,editor.project.frames)
        editor.project.delete_range(30,60)
        editor.project.delete_range(60,61)
        editor.project_changed(60)
        editor.speed.setCurrentIndex(6)
        editor.output_directory.setText(str(self.result.parent));editor.output_name.setText('神录剪 中文倍速测试')
        self.phase='exporting';editor.start_export()
        if not editor.busy:self.finish(False,'Export did not start')

    def probe(self,path):
        return json.loads(subprocess.check_output([shutil.which('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(path)],
            env={k:v for k,v in __import__('os').environ.items() if k!='LD_LIBRARY_PATH'}))

    def exported(self,passed,path):
        if self.phase!='exporting':return
        if not passed:self.finish(False,'Export failed');return
        metadata=self.probe(path);video=next(s for s in metadata['streams'] if s['codec_type']=='video')
        self.results['editing_export']=video['codec_name']=='h264' and abs(float(metadata['format']['duration'])-(119/30/2))<.06
        self.results['audio_retained']=any(s['codec_type']=='audio' for s in metadata['streams'])
        self.results['original_preserved']=hashlib.sha256(self.source.read_bytes()).hexdigest()==self.original_hash
        self.phase='recording';recorder=self.window.recorder
        recorder.directory.setText(str(self.result.parent));recorder.name.setText('神录剪 录屏回归')
        recorder.timestamp.setChecked(False);recorder.minimize.setChecked(False)
        recorder.area.setCurrentIndex(recorder.area.count()-1);recorder.x.setValue(0);recorder.y.setValue(0)
        recorder.capture_w.setValue(960);recorder.capture_h.setValue(800)
        recorder.resolution.setCurrentIndex(recorder.resolution.count()-1)
        recorder.output_w.setValue(640);recorder.output_h.setValue(480);recorder.fps.setValue(24)
        recorder.start_recording();QTimer.singleShot(2700,recorder.stop_recording)

    def recorded(self,code,status):
        if self.phase!='recording':return
        if code or not self.window.recorder.last_saved:self.finish(False,'Recording regression failed');return
        metadata=self.probe(self.window.recorder.last_saved);stream=metadata['streams'][0]
        self.results['recording_regression']=(stream['width']==640 and stream['height']==480 and stream['avg_frame_rate']=='24/1')
        self.phase='recorded-import';self.window.import_recording()

    def finish(self,passed,reason=''):
        if self.done:return
        self.done=True
        payload={'passed':bool(passed),'checks':self.results,'reason':reason}
        self.result.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(json.dumps(payload,ensure_ascii=False),flush=True)
        self.window.editor.shutdown_preview()
        QApplication.instance().exit(0 if passed else 1)


def main():
    parser=argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--screenshot')
    parser.add_argument('--integration-test')
    parser.add_argument('--preview-test')
    parser.add_argument('--timeline-test')
    parser.add_argument('--controls-test')
    parser.add_argument('--audio-test')
    parser.add_argument('--test-input')
    args=parser.parse_args()
    # VAAPI post-processing fails to negotiate CPU RGB frames on this desktop.
    # Use GStreamer's documented per-process ranks; other apps are unaffected.
    # https://gstreamer.freedesktop.org/documentation/gstreamer/running.html
    ranks='avdec_h264:512,avdec_h265:512,avdec_vp9:512,avdec_mpeg4:512,vaapipostproc:0'
    existing=os.environ.get('GST_PLUGIN_FEATURE_RANK','')
    os.environ['GST_PLUGIN_FEATURE_RANK']=(existing+',' if existing else '')+ranks
    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling)
    app=QApplication([sys.argv[0]]);app.setApplicationName(APP_ID);app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID);app.setStyle('Fusion')
    app.setStyleSheet(STYLE.replace('__CHEVRON__',str(RESOURCE_DIR/'assets/chevron.svg'))+EXTRA_STYLE)
    window=StudioWindow();window.showMaximized()
    if args.screenshot:QTimer.singleShot(800,lambda:(window.grab().save(args.screenshot),app.exit(0)))
    if args.integration_test:
        if not args.test_input:parser.error('--test-input is required for integration testing')
        window.check=IntegrationCheck(window,args.test_input,args.integration_test)
    if args.preview_test:
        if not args.test_input:parser.error('--test-input is required for preview testing')
        from preview_check import PreviewCheck
        window.check=PreviewCheck(window,args.test_input,args.preview_test)
    if args.timeline_test:
        if not args.test_input:parser.error('--test-input folder is required for timeline testing')
        from timeline_check import TimelineCheck
        window.check=TimelineCheck(window,args.test_input,args.timeline_test)
    if args.controls_test:
        if not args.test_input:parser.error('--test-input folder is required for controls testing')
        from controls_check import ControlsCheck
        window.check=ControlsCheck(window,args.test_input,args.controls_test)
    if args.audio_test:
        if not args.test_input:parser.error('--test-input folder is required for audio testing')
        from audio_check import AudioCheck
        window.check=AudioCheck(window,args.test_input,args.audio_test)
    return app.exec_()


if __name__=='__main__':raise SystemExit(main())
