#!/usr/bin/env python3
"""神录剪的录屏面板：保留原 FFmpeg 录制行为。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from PyQt5.QtCore import QProcess, QSettings, QStandardPaths, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget,
)
from app.recording.commands import RecordingOptions, ffmpeg_arguments, output_path
from app.recording.area_selector import AreaSelector
from app.recording.geometry import CaptureGeometry,screen_choices
from app.common.environment import clean_child_environment, clean_subprocess_environment, subprocess_options
from app.common.resources import RESOURCE_DIR, media_tool

APP_ID = "shenlujian"
APP_NAME = "神录剪"
class RecorderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} · FFmpeg 录屏")
        self.setWindowIcon(QIcon(str(RESOURCE_DIR / "assets/shenlujian.svg")))
        self.resize(850, 1000)
        self.setMinimumSize(700, 710)
        self.windows = sys.platform == "win32"
        self.wayland = not self.windows and os.environ.get("XDG_SESSION_TYPE")=="wayland"
        self.capture_ready = False
        self.recording_cancelled = False
        self.settings = QSettings("Codeme", APP_ID)
        self.process = QProcess(self)
        self.process.setProcessEnvironment(clean_child_environment())
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        self.process.started.connect(self.started)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.readyReadStandardOutput.connect(self.read_progress)
        self.process.errorOccurred.connect(self.process_error)
        self.process.finished.connect(self.finished)
        self.progress_buffer = ""
        self.error_tail = ""
        self.state = "idle"
        self.destination = None
        self.last_saved = None
        self.started_at = 0
        self.output_seconds = 0
        self.output_frames = 0
        self.close_after_stop = False
        self.stop_when_started = False
        self.minimize_pending = False
        self.self_test = False
        self.test_result = None
        self.video_info = None
        self.ffmpeg = media_tool("ffmpeg")
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.update_timer)
        self.build_ui()
        self.load_settings()
        if self.wayland:
            self.minimize.setChecked(False);self.minimize.setEnabled(False)
            self.minimize.setToolTip("Wayland 全局按键由桌面控制，保持窗口可见以使用停止按钮。")
        self.connect_settings()
        self.update_preview()
        app=QApplication.instance()
        self.screen_refresh=QTimer(self);self.screen_refresh.setSingleShot(True);self.screen_refresh.setInterval(200)
        self.screen_refresh.timeout.connect(self.refresh_capture_geometry)
        self.screen_connections=set()
        def connect_screens(*_):
            for screen in QApplication.screens():
                if screen not in self.screen_connections:
                    screen.geometryChanged.connect(lambda *_:self.screen_refresh.start())
                    screen.logicalDotsPerInchChanged.connect(lambda *_:self.screen_refresh.start())
                    self.screen_connections.add(screen)
            self.screen_refresh.start()
        app.screenAdded.connect(connect_screens);app.screenRemoved.connect(connect_screens);connect_screens()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip(APP_NAME)
            self.tray.activated.connect(self.tray_clicked)
            self.tray.show()
        else:
            self.tray = None

    def card(self, title):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setObjectName("section")
        layout.addWidget(label)
        return card, layout

    def label(self, text):
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    def spin(self, low, high, value, suffix=""):
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    def build_ui(self):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(15)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded if self.windows else Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        outer.addWidget(scroll,1)
        self.setCentralWidget(central)
        header = QHBoxLayout()
        title = QLabel("录")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        self.parameter_box = QWidget()
        parameter_layout = QVBoxLayout(self.parameter_box)
        parameter_layout.setContentsMargins(0, 0, 0, 0)
        parameter_layout.setSpacing(14)
        layout.addWidget(self.parameter_box)

        picture, picture_layout = self.card("画面")
        parameter_layout.addWidget(picture)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(7)
        picture_layout.addLayout(grid)
        self.area = QComboBox()
        self.capture_geometry = CaptureGeometry.detect(QApplication.screens())
        united = self.capture_geometry.root
        self.desktop_geometry = united
        self.populate_capture_regions()
        self.resolution = QComboBox()
        for text, dimensions in [("原始尺寸", (0,0)), ("2K · 2560 × 1440", (2560,1440)),
                                  ("1080p · 1920 × 1080", (1920,1080)), ("720p · 1280 × 720", (1280,720)),
                                  ("480p · 854 × 480", (854,480)), ("4K · 3840 × 2160", (3840,2160)), ("自定义尺寸", None)]:
            self.resolution.addItem(text, dimensions)
        self.fps = self.spin(1,120,30," 帧 / 秒")
        for column, (name, widget) in enumerate([( "录制区域", self.area), ("输出分辨率", self.resolution), ("帧率",self.fps)]):
            grid.addWidget(self.label(name),0,column)
            grid.addWidget(widget,1,column)
        grid.setColumnStretch(0,2)
        grid.setColumnStretch(1,2)
        grid.setColumnStretch(2,1)
        self.custom_area = QWidget()
        self.custom_area.setObjectName("inlineRow")
        row = QHBoxLayout(self.custom_area)
        row.setContentsMargins(0,0,0,0)
        self.x = self.spin(united.x(),max(united.x()+united.width()-2,united.x()),united.x())
        self.y = self.spin(united.y(),max(united.y()+united.height()-2,united.y()),united.y())
        self.capture_w = self.spin(2,max(united.width(),2),united.width())
        self.capture_h = self.spin(2,max(united.height(),2),united.height())
        for name, widget in [("左",self.x),("上",self.y),("宽",self.capture_w),("高",self.capture_h)]:
            row.addWidget(self.label(name)); row.addWidget(widget)
        picture_layout.addWidget(self.custom_area)
        self.custom_size = QWidget()
        self.custom_size.setObjectName("inlineRow")
        row = QHBoxLayout(self.custom_size)
        row.setContentsMargins(0,0,0,0)
        self.output_w = self.spin(2,32766,1920)
        self.output_h = self.spin(2,32766,1080)
        self.output_w.setSingleStep(2); self.output_h.setSingleStep(2)
        row.addWidget(self.label("输出宽度")); row.addWidget(self.output_w)
        row.addWidget(self.label("输出高度")); row.addWidget(self.output_h)
        picture_layout.addWidget(self.custom_size)
        self.cursor = QCheckBox("录制鼠标指针")
        self.cursor.setChecked(True)
        capture_tools = QHBoxLayout()
        capture_tools.addWidget(self.cursor)
        capture_tools.addStretch()
        self.select_area_button = QPushButton("鼠标框选区域…")
        self.select_area_button.clicked.connect(self.select_area)
        if self.wayland:
            self.select_area_button.setEnabled(False)
            self.select_area_button.setToolTip("Wayland 由系统对话框选择屏幕；自定义区域可填写屏幕内的像素坐标。")
        capture_tools.addWidget(self.select_area_button)
        picture_layout.addLayout(capture_tools)
        self.capture_size_label=self.label("");self.capture_size_label.setWordWrap(True);picture_layout.addWidget(self.capture_size_label)
        for control in (self.x,self.y,self.capture_w,self.capture_h):
            control.setToolTip("所选共享屏幕内的实际像素，左上角为 0,0。" if self.wayland else "Windows 桌面实际像素；左侧或上方屏幕的坐标可为负数，框选自动换算显示缩放。" if self.windows else "X11 桌面实际像素；鼠标框选会自动换算显示缩放。")
        self.resolution.setToolTip("输出支持原始尺寸、1080p、2K、4K及自定义；保持画面比例，奇数尺寸向下对齐到偶数。")

        quality_card, quality_layout = self.card("清晰度与性能")
        parameter_layout.addWidget(quality_card)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        self.quality = QComboBox()
        for text, value in [("高清 · 画面更细腻",18),("标准 · 推荐",23),("省空间 · 文件更小",28),("自定义",None)]:
            self.quality.addItem(text,value)
        self.quality.setCurrentIndex(1)
        self.preset = QComboBox()
        for text, value in [("极速 · ultrafast", "ultrafast"), ("很快 · superfast","superfast"),
                            ("快速 · veryfast","veryfast"), ("均衡 · fast","fast"), ("压缩优先 · medium","medium")]:
            self.preset.addItem(text,value)
        grid.addWidget(self.label("视频清晰度"),0,0); grid.addWidget(self.quality,1,0)
        grid.addWidget(self.label("编码速度"),0,1); grid.addWidget(self.preset,1,1)
        grid.setColumnStretch(0,1); grid.setColumnStretch(1,1)
        quality_layout.addLayout(grid)
        self.crf_row = QWidget()
        self.crf_row.setObjectName("inlineRow")
        row = QHBoxLayout(self.crf_row)
        row.setContentsMargins(0,0,0,0)
        self.crf = self.spin(0,35,23)
        row.addWidget(self.label("CRF · 数值越小越清晰")); row.addWidget(self.crf); row.addStretch()
        quality_layout.addWidget(self.crf_row)

        file_card, file_layout = self.card("保存")
        parameter_layout.addWidget(file_card)
        name_row = QHBoxLayout()
        self.name = QLineEdit("linglong2_lower_fc")
        self.name.setPlaceholderText("视频名称，无需填写 .mp4")
        self.timestamp = QCheckBox("名称加时间")
        self.timestamp.setChecked(True)
        name_row.addWidget(self.name,1); name_row.addWidget(self.timestamp)
        file_layout.addLayout(name_row)
        path_row = QHBoxLayout()
        self.directory = QLineEdit(str(Path.home()/"shenlujian"/"video"))
        browse = QPushButton("选择目录…")
        browse.clicked.connect(self.browse_directory)
        path_row.addWidget(self.directory,1); path_row.addWidget(browse)
        file_layout.addLayout(path_row)
        self.path_preview = QLabel()
        self.path_preview.setObjectName("muted")
        self.path_preview.setWordWrap(True)
        self.path_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        file_layout.addWidget(self.path_preview)

        row = QHBoxLayout()
        self.minimize = QCheckBox("开始后最小化")
        self.minimize.setChecked(True)
        row.addWidget(self.minimize)
        row.addStretch()
        self.open_folder = QPushButton("打开输出目录")
        self.open_folder.clicked.connect(self.open_output_directory)
        row.addWidget(self.open_folder)
        layout.addLayout(row)
        status_card, status_layout = self.card("录制状态")
        status_layout.takeAt(0).widget().deleteLater()
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(26,6,26,22)
        footer_layout.addWidget(status_card)
        outer.addWidget(footer)
        row = QHBoxLayout()
        status_texts = QVBoxLayout()
        self.status = QLabel("准备就绪")
        self.status.setObjectName("section")
        self.elapsed = QLabel("00:00:00")
        self.elapsed.setObjectName("timer")
        status_texts.addWidget(self.status); status_texts.addWidget(self.elapsed)
        row.addLayout(status_texts); row.addStretch()
        self.start_button = QPushButton("●  开始录制")
        self.start_button.setObjectName("record")
        self.start_button.clicked.connect(self.start_recording)
        self.start_button.setText("● 开始录制 F9");self.start_button.setToolTip("F9 开始录制，窗口最小化后也可使用。")
        self.stop_button = QPushButton("■  停止并保存")
        self.stop_button.setObjectName("stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recording)
        self.stop_button.setText("■ 停止保存 F10");self.stop_button.setToolTip("F10 停止录制并保存，窗口最小化后也可使用。")
        row.addWidget(self.start_button); row.addWidget(self.stop_button)
        status_layout.addLayout(row)
        self.detail = self.label("")
        self.detail.setWordWrap(True)
        detail_row = QHBoxLayout()
        detail_row.addWidget(self.detail,1)
        self.open_video = QPushButton("打开上次视频")
        self.open_video.setEnabled(False)
        self.open_video.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_saved))))
        detail_row.addWidget(self.open_video)
        status_layout.addLayout(detail_row)

        self.diagnostics_button = QPushButton("查看命令与日志 ▾")
        self.diagnostics_button.setFlat(True)
        self.diagnostics_button.setCheckable(True)
        self.diagnostics_button.toggled.connect(self.toggle_diagnostics)
        layout.addWidget(self.diagnostics_button, alignment=Qt.AlignLeft)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumHeight(150)
        self.logs.document().setMaximumBlockCount(300)
        self.logs.hide()
        layout.addWidget(self.logs)
        layout.addStretch()

    def populate_capture_regions(self,selected='fullscreen'):
        screen=QApplication.primaryScreen();name=screen.name() if screen else ''
        self.area.blockSignals(True);self.area.clear()
        choices=screen_choices(self.capture_geometry,name)
        if self.wayland:choices=[('全屏录制（系统选择屏幕）',self.capture_geometry.root,'fullscreen'),('自定义区域（屏幕内坐标）',None,'custom')]
        for label,rectangle,key in choices:
            data=None if rectangle is None else (rectangle.x(),rectangle.y(),rectangle.width(),rectangle.height())
            self.area.addItem(label,data);self.area.setItemData(self.area.count()-1,key,Qt.UserRole+1)
        index=next((i for i in range(self.area.count()) if self.area.itemData(i,Qt.UserRole+1)==selected),0)
        self.area.setCurrentIndex(index);self.area.blockSignals(False)

    def refresh_capture_geometry(self,*_):
        if self.state!='idle':self.screens_dirty=True;return
        self.screens_dirty=False
        selected=self.area.currentData(Qt.UserRole+1) or 'fullscreen'
        self.capture_geometry=CaptureGeometry.detect(QApplication.screens());r=self.capture_geometry.root;self.desktop_geometry=r
        self.populate_capture_regions(selected)
        ranges=[(self.x,0,32766),(self.y,0,32766),(self.capture_w,2,32766),(self.capture_h,2,32766)] if self.wayland else [(self.x,r.x(),r.x()+r.width()-2),(self.y,r.y(),r.y()+r.height()-2),(self.capture_w,2,r.width()),(self.capture_h,2,r.height())]
        for control,low,high in ranges:control.setRange(low,max(low,high))
        self.update_preview()

    def select_area(self):
        if self.wayland or self.state != "idle" or getattr(self,"area_selector",None):return
        self.refresh_capture_geometry()
        self.selection_host = self.window()
        self.selection_window_state = self.selection_host.windowState()
        self.selection_host.hide()
        self.select_area_button.setEnabled(False)
        QTimer.singleShot(150,self.show_area_selector)

    def show_area_selector(self):
        self.area_selector = AreaSelector(self.capture_geometry.logical_bounds,self.capture_geometry.to_native)
        self.area_selector.selected.connect(self.apply_selected_area)
        self.area_selector.cancelled.connect(self.restore_after_selection)
        self.area_selector.show()
        self.area_selector.raise_()
        self.area_selector.activateWindow()
        self.area_selector.setFocus()
        self.area_selector.grabKeyboard()

    def apply_selected_area(self,rectangle):
        rectangle=self.capture_geometry.to_native(rectangle)
        if rectangle.width()<2 or rectangle.height()<2:self.restore_after_selection();return
        for spin,value in ((self.x,rectangle.x()),(self.y,rectangle.y()),
                           (self.capture_w,rectangle.width()),(self.capture_h,rectangle.height())):
            spin.blockSignals(True);spin.setValue(value);spin.blockSignals(False)
        self.area.setCurrentIndex(self.area.count()-1)
        self.update_preview()
        self.restore_after_selection()

    def restore_after_selection(self):
        self.area_selector = None
        self.select_area_button.setEnabled(True)
        state = self.selection_window_state & ~Qt.WindowMinimized
        if self.selection_host.windowState() != state:self.selection_host.setWindowState(state)
        self.selection_host.show()
        self.selection_host.raise_()
        self.selection_host.activateWindow()

    def connect_settings(self):
        for combo in (self.area,self.resolution,self.quality,self.preset): combo.currentIndexChanged.connect(self.update_preview)
        for spin in (self.fps,self.x,self.y,self.capture_w,self.capture_h,self.output_w,self.output_h,self.crf): spin.valueChanged.connect(self.update_preview)
        for edit in (self.name,self.directory): edit.textChanged.connect(self.update_preview)
        for check in (self.timestamp,self.cursor): check.toggled.connect(self.update_preview)

    def load_settings(self):
        self.area.setCurrentIndex(0)
        for key, widget in [("resolution",self.resolution),("quality",self.quality),("preset",self.preset)]:
            try: index=int(self.settings.value(key,widget.currentIndex()))
            except (ValueError,TypeError): continue
            if key=='resolution':
                saved=self.settings.value('resolution_size',None)
                if saved is not None:
                    try:target=None if saved=='custom' else tuple(map(int,str(saved).split('x')))
                    except (ValueError,TypeError):target=(0,0)
                    index=next((i for i in range(widget.count()) if widget.itemData(i)==target),0)
                elif index==5:index=widget.count()-1
            if 0 <= index < widget.count(): widget.setCurrentIndex(index)
        for key, widget in [("fps",self.fps),("x",self.x),("y",self.y),("capture_w",self.capture_w),("capture_h",self.capture_h),
                            ("output_w",self.output_w),("output_h",self.output_h),("crf",self.crf)]:
            try: widget.setValue(int(self.settings.value(key,widget.value())))
            except (ValueError,TypeError): pass
        for key, widget in [("name",self.name),("directory",self.directory)]:
            widget.setText(str(self.settings.value(key,widget.text())))
        for key, widget in [("timestamp",self.timestamp),("cursor",self.cursor),("minimize",self.minimize)]:
            widget.setChecked(str(self.settings.value(key,widget.isChecked())).lower() in {"true","1"})

    def save_settings(self):
        for key, widget in [("area",self.area),("resolution",self.resolution),("quality",self.quality),("preset",self.preset)]:
            self.settings.setValue(key,widget.currentIndex())
        for key, widget in [("fps",self.fps),("x",self.x),("y",self.y),("capture_w",self.capture_w),("capture_h",self.capture_h),
                            ("output_w",self.output_w),("output_h",self.output_h),("crf",self.crf)]:
            self.settings.setValue(key,widget.value())
        for key, widget in [("name",self.name),("directory",self.directory)]: self.settings.setValue(key,widget.text())
        for key, widget in [("timestamp",self.timestamp),("cursor",self.cursor),("minimize",self.minimize)]:
            self.settings.setValue(key,widget.isChecked())
        size=self.resolution.currentData()
        self.settings.setValue('resolution_size','custom' if size is None else f'{size[0]}x{size[1]}')
        self.settings.sync()

    def collect_options(self):
        area = self.area.currentData()
        if area is None: area = (self.x.value(),self.y.value(),self.capture_w.value(),self.capture_h.value())
        x,y,width,height = area
        bounds = self.desktop_geometry
        if not self.wayland and (x < bounds.x() or y < bounds.y() or x+width > bounds.x()+bounds.width() or y+height > bounds.y()+bounds.height()):
            raise ValueError("录制区域超出屏幕范围，请调整左、上、宽、高。")
        size = self.resolution.currentData()
        if size is None: size = (self.output_w.value(),self.output_h.value())
        crf = self.quality.currentData()
        if crf is None: crf = self.crf.value()
        return RecordingOptions("desktop" if self.windows else "pipewire" if self.wayland else os.environ.get("DISPLAY",""),x,y,width,height,self.fps.value(),crf,
                                self.preset.currentData(),*size,self.cursor.isChecked(),
                                capture_backend="gdigrab" if self.windows else "x11grab")

    def update_preview(self, *_):
        self.custom_area.setVisible(self.area.currentData() is None)
        self.custom_size.setVisible(self.resolution.currentData() is None)
        self.crf_row.setVisible(self.quality.currentData() is None)
        try:
            options=self.collect_options();w,h=options.video_size
            self.capture_size_label.setText('按系统共享画面的原始尺寸录制' if self.wayland and self.area.currentData() is not None and self.resolution.currentData()==(0,0) else '按所选屏幕的原始尺寸录制' if self.area.currentData() is not None and self.resolution.currentData()==(0,0) else f'输出 {w} × {h}')
        except ValueError as error:self.capture_size_label.setText(str(error))
        try:
            path = output_path(self.directory.text(),self.name.text(),self.timestamp.isChecked())
            self.path_preview.setText(str(path))
            self.path_preview.setToolTip(str(path))
        except ValueError as error:
            self.path_preview.setText(str(error))

    def browse_directory(self):
        path = QFileDialog.getExistingDirectory(self,"选择输出目录",self.directory.text())
        if path: self.directory.setText(path)

    def open_output_directory(self):
        path = Path(self.directory.text()).expanduser()
        if path.is_dir(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else: self.report_error("输出目录尚不存在，开始录制时会自动创建。")

    def toggle_diagnostics(self, visible):
        self.logs.setVisible(visible)
        self.diagnostics_button.setText("收起命令与日志 ▴" if visible else "查看命令与日志 ▾")

    def report_error(self, message):
        self.error_tail = message
        self.status.setText("录制未完成")
        self.detail.setText(message)
        self.logs.append(message)
        if not self.self_test: QMessageBox.warning(self,APP_NAME,message)

    def start_recording(self):
        if self.state != "idle": return
        if not self.ffmpeg:
            self.report_error("未找到 ffmpeg，请安装 ffmpeg 后重新打开应用。")
            return
        try:
            if getattr(self,'area_selector',None):return
            self.refresh_capture_geometry()
            options = self.collect_options()
            options.validate()
            destination = output_path(self.directory.text(),self.name.text(),self.timestamp.isChecked())
            destination.parent.mkdir(parents=True,exist_ok=True)
            if not os.access(destination.parent,os.W_OK): raise ValueError("输出目录没有写入权限。")
            arguments = ffmpeg_arguments(options,destination)
            program=self.ffmpeg
            if self.wayland:
                helper=RESOURCE_DIR/'app'/'recording'/'wayland_capture.py'
                if not helper.exists():raise ValueError('Wayland 录屏组件缺失，请重新安装。')
                config={'ffmpeg':self.ffmpeg,'destination':str(destination),'fps':options.fps,'crf':options.crf,'preset':options.preset,'cursor':options.cursor,'output':[options.output_width,options.output_height],'crop':[options.x,options.y,options.width,options.height] if self.area.currentData() is None else None}
                program='/usr/bin/python3';arguments=[str(helper),json.dumps(config)]
        except (ValueError,OSError) as error:
            self.report_error(str(error)); return
        self.destination = destination
        self.video_info = {"width":options.video_size[0],"height":options.video_size[1],"fps":options.fps}
        self.save_settings()
        self.capture_ready=False;self.recording_cancelled=False
        self.error_tail = ""
        self.progress_buffer = ""
        self.output_seconds = 0
        self.output_frames = 0
        self.elapsed.setText("00:00:00")
        self.detail.setText(str(destination))
        self.logs.clear()
        self.logs.append(subprocess.list2cmdline([program,*arguments]) if self.windows else shlex.join([program,*arguments]))
        self.state = "starting"
        self.status.setText("正在启动…")
        self.parameter_box.setEnabled(False)
        self.start_button.setEnabled(False)
        self.minimize.setEnabled(False)
        self.open_video.setEnabled(False)
        self.process.setProgram(program)
        self.process.setArguments(arguments)
        self.process.start()

    def started(self):
        if self.wayland and not self.capture_ready:
            self.stop_button.setEnabled(True);self.status.setText('请在系统对话框中选择共享屏幕…')
            if self.stop_when_started:self.process.write(b'q\n')
            return
        self.state = "recording"
        self.status.setText("● 正在录制")
        self.started_at = time.monotonic()
        self.stop_button.setEnabled(True)
        self.timer.start()
        if self.tray: self.tray.setToolTip(f"{APP_NAME} · 正在录制")
        if self.close_after_stop or self.stop_when_started:
            self.stop_recording()
            return
        if self.self_test: QTimer.singleShot(2500,self.stop_recording)

    def read_progress(self):
        self.progress_buffer += bytes(self.process.readAllStandardOutput()).decode("utf-8",errors="replace")
        while "\n" in self.progress_buffer:
            line,self.progress_buffer = self.progress_buffer.split("\n",1)
            if self.wayland and line.startswith('{'):
                try:
                    event=json.loads(line)
                    if event.get('event')=='recording':
                        self.capture_ready=True;self.video_info={key:event[key] for key in ('width','height','fps')};self.started()
                    elif event.get('event')=='cancelled':self.recording_cancelled=True
                except (ValueError,KeyError):pass
            if line.startswith('frame='):
                try:self.output_frames=int(line.split('=',1)[1])
                except ValueError:pass
                if self.output_frames>0 and self.stop_when_started and self.state=='recording':self.stop_recording()
            if line.startswith("out_time_us="):
                try: self.output_seconds = int(line.split("=",1)[1])/1_000_000
                except ValueError: pass
                if self.state == "recording" and self.minimize.isChecked() and not self.minimize_pending and not self.self_test:
                    self.minimize_pending = True
                    self.showMinimized()

    def read_errors(self):
        text = bytes(self.process.readAllStandardError()).decode("utf-8",errors="replace")
        self.error_tail = (self.error_tail+text)[-6000:]
        if text.strip(): self.logs.append(text.strip())

    def update_timer(self):
        seconds = int(max(0,time.monotonic()-self.started_at))
        self.elapsed.setText(f"{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}")
        if self.destination and self.destination.exists():
            size = self.destination.stat().st_size/(1024*1024)
            self.detail.setText(f"{self.destination}\n已写入 {size:.1f} MB")
        if self.tray: self.tray.setToolTip(f"{APP_NAME} · {self.elapsed.text()} · 点击打开")

    def stop_recording(self):
        if self.state=='starting':
            self.stop_when_started=True
            if self.wayland:self.process.write(b'q\n');self.status.setText('正在取消屏幕共享…')
            else:self.status.setText('启动后停止并保存…')
            return
        if self.state != "recording": return
        if not self.output_frames:
            self.stop_when_started=True;self.status.setText('等待首帧后停止并保存…');return
        self.state = "saving"
        self.status.setText("正在保存 MP4…")
        self.stop_button.setEnabled(False)
        self.process.write(b"q\n")
        self.process.closeWriteChannel()

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.reset_controls()
            self.report_error("FFmpeg 启动失败："+self.process.errorString())
            if self.self_test: self.finish_test(False)
            elif self.close_after_stop: self.close()

    def reset_controls(self):
        self.state = "idle"
        self.timer.stop()
        self.parameter_box.setEnabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.minimize.setEnabled(not self.wayland)
        self.minimize_pending = False;self.stop_when_started=False
        if getattr(self,'screens_dirty',False):self.screen_refresh.start()
        if self.tray: self.tray.setToolTip(APP_NAME)

    def finished(self, code, status):
        self.read_errors()
        self.read_progress()
        self.reset_controls()
        success = code == 0 and status == QProcess.NormalExit and self.destination and self.destination.is_file() and self.destination.stat().st_size > 0
        if self.recording_cancelled:
            self.status.setText("已取消录制");self.detail.setText("准备就绪")
        elif success:
            self.last_saved = self.destination
            self.status.setText("✓ 已保存")
            self.detail.setText(str(self.last_saved))
            self.open_video.setEnabled(True)
            self.update_preview()
            if not self.self_test:
                self.showNormal(); self.raise_()
        else:
            message = self.error_tail.strip() or f"FFmpeg 异常退出（{code}），请查看日志。"
            self.report_error(message)
        if self.self_test: self.finish_test(bool(success))
        if self.close_after_stop:
            self.close_after_stop = False
            self.close()

    def tray_clicked(self, reason):
        if reason in (QSystemTrayIcon.Trigger,QSystemTrayIcon.DoubleClick):
            self.showNormal(); self.raise_(); self.activateWindow()

    def closeEvent(self, event):
        if self.state != "idle":
            self.close_after_stop = True
            self.stop_recording()
            event.ignore()
        else:
            self.save_settings()
            if self.tray: self.tray.hide()
            event.accept()

    def finish_test(self, success):
        result = {"passed":success,"path":str(self.destination),"expected":self.video_info,"error":self.error_tail}
        if success:
            try:
                output = subprocess.check_output([media_tool("ffprobe") or "ffprobe","-v","error","-show_streams","-show_format","-of","json",str(self.destination)],env=clean_subprocess_environment(),**subprocess_options())
                metadata=json.loads(output)
                stream=metadata["streams"][0]
                numerator,denominator=map(int,stream["avg_frame_rate"].split("/"))
                result["actual"]={"codec":stream["codec_name"],"width":stream["width"],"height":stream["height"],"fps":numerator/denominator,"duration":float(metadata["format"]["duration"])}
                expected=self.video_info
                result["passed"]=(stream["codec_name"]=="h264" and stream["width"]==expected["width"] and stream["height"]==expected["height"] and numerator/denominator==expected["fps"] and result["actual"]["duration"]>1)
            except Exception as error:
                result["passed"]=False;result["error"]=str(error)
        Path(self.test_result).write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False),flush=True)
        QApplication.instance().exit(0 if result["passed"] else 1)
