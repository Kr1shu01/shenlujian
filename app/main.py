#!/usr/bin/env python3
"""神录剪 combines the existing recorder with a basic frame editor."""
import argparse
import os
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QSplitter, QSystemTrayIcon, QVBoxLayout, QWidget, QShortcut
from app.recording.panel import RecorderWindow
from app.common.resources import RESOURCE_DIR
from app.common.style import STYLE, EXTRA_STYLE
from app.editor.panel import EditorPanel
from app.common.hotkeys import GlobalHotkeys

APP_ID='shenlujian'
APP_NAME='神录剪'
DESCRIPTION='随手一录，轻松一剪。'



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
        from tests.checks.integration_check import IntegrationCheck
        window.check=IntegrationCheck(window,args.test_input,args.integration_test)
    if args.preview_test:
        if not args.test_input:parser.error('--test-input is required for preview testing')
        from tests.checks.preview_check import PreviewCheck
        window.check=PreviewCheck(window,args.test_input,args.preview_test)
    if args.timeline_test:
        if not args.test_input:parser.error('--test-input folder is required for timeline testing')
        from tests.checks.timeline_check import TimelineCheck
        window.check=TimelineCheck(window,args.test_input,args.timeline_test)
    if args.controls_test:
        if not args.test_input:parser.error('--test-input folder is required for controls testing')
        from tests.checks.controls_check import ControlsCheck
        window.check=ControlsCheck(window,args.test_input,args.controls_test)
    if args.audio_test:
        if not args.test_input:parser.error('--test-input folder is required for audio testing')
        from tests.checks.audio_check import AudioCheck
        window.check=AudioCheck(window,args.test_input,args.audio_test)
    return app.exec_()


if __name__=='__main__':raise SystemExit(main())
