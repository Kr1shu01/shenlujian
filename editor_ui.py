from __future__ import annotations
import json,math,os,shutil,uuid,time
from pathlib import Path
from PyQt5.QtCore import QProcess,QSettings,Qt,QTimer,QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtMultimedia import QMediaContent,QMediaPlayer
from PyQt5.QtWidgets import (QApplication,QCheckBox,QComboBox,QDoubleSpinBox,QFileDialog,QFrame,QHBoxLayout,QLabel,QLineEdit,
    QMessageBox,QProgressBar,QPushButton,QScrollArea,QShortcut,QTextEdit,QVBoxLayout,QWidget)
from PyQt5.QtCore import pyqtSignal
from recorder_ui import clean_child_environment
from media_library import MediaLibrary
from preview_ui import CpuVideoSurface,PreviewProxy,VideoCanvas
from project_model import Project,project_export_arguments
from project_timeline import ProjectTimeline
from recording import output_path
from video_sizes import export_size
from audio_preview import AudioPreview


def clock(seconds):
    ms=max(0,round(seconds*1000));return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d}.{ms%1000:03d}'


class EditorPanel(QWidget):
    video_loaded=pyqtSignal()
    export_finished=pyqtSignal(bool,str)
    def __init__(self):
        super().__init__();self.setAcceptDrops(True)
        self.settings=QSettings('Codeme','shenlujian');self.project=Project();self.pending_additions=[]
        self.current_frame=0;self.info=None;self.current_source=None;self.active_index=None
        self.busy=False;self.cancelled=False;self.result_path=None;self.pending_path=None;self.last_export=None
        self.expected_duration=0;self.error_tail='';self.progress_buffer='';self.test_mode=False;self.output_name_custom=False
        self.ffmpeg=shutil.which('ffmpeg');self.ffprobe=shutil.which('ffprobe')
        self.wanted_play=False;self.media_seek_pending=False;self.preview_path=None;self.preview_sources={}
        self._switching=False;self._advancing=False;self._source_position=0;self._expected_epoch=0;self._seek_gate=None
        self._has_frame_timestamps=False;self._proxy_requested=None;self.thumbnail_serial=0;self.thumbnail_process=None
        self._playback_generation=0;self._advance_pending=False;self._clock_frame=0;self._clock_at=time.monotonic();self._tail_mode=False
        self.player=QMediaPlayer(self,QMediaPlayer.VideoSurface);self.player.setNotifyInterval(20)
        self.player.positionChanged.connect(self.position_changed);self.player.stateChanged.connect(self.play_state_changed)
        self.player.mediaStatusChanged.connect(self.media_status_changed);self.player.error.connect(self.media_error)
        self.encoder=QProcess(self);self.encoder.setProcessEnvironment(clean_child_environment())
        self.encoder.readyReadStandardError.connect(self.read_errors);self.encoder.readyReadStandardOutput.connect(self.read_progress)
        self.encoder.finished.connect(self.encoding_finished);self.encoder.errorOccurred.connect(self.encoding_error)
        self.thumbnail_timer=QTimer(self);self.thumbnail_timer.setSingleShot(True);self.thumbnail_timer.setInterval(80)
        self.thumbnail_timer.timeout.connect(self.request_thumbnail)
        self.build_ui()
        self.surface=CpuVideoSurface(self);self.surface.frame_received.connect(self.video_frame_ready);self.player.setVideoOutput(self.surface)
        self.audio_preview=AudioPreview(self,self.project)
        self.track_timer=QTimer(self);self.track_timer.setInterval(40);self.track_timer.timeout.connect(self.tick_tracks);self.track_timer.start()
        self.proxy=PreviewProxy(self,self.ffmpeg,clean_child_environment(),self.proxy_progress,self.proxy_ready,self.proxy_error)
        for key,callback in [('Ctrl+Z',self.undo_project),('Ctrl+Shift+Z',self.redo_project),('Delete',self.delete_selected_clip),('Left',lambda:self.jump_seconds(-5)),('Right',lambda:self.jump_seconds(5))]:
            shortcut=QShortcut(key,self,activated=callback);shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.playback_timer=QTimer(self);self.playback_timer.setInterval(200);self.playback_timer.timeout.connect(self.ensure_playing);self.playback_timer.start()
        self.update_project_controls();QTimer.singleShot(0,self.restore_library)

    def button(self,text,callback):
        button=QPushButton(text);button.clicked.connect(callback);return button
    def card(self,title):
        frame=QFrame();frame.setObjectName('card');layout=QVBoxLayout(frame)
        layout.setContentsMargins(14,12,14,14);layout.setSpacing(9)
        label=QLabel(title);label.setObjectName('section');layout.addWidget(label);return frame,layout

    def build_ui(self):
        outer=QVBoxLayout(self);outer.setContentsMargins(22,22,24,22);outer.setSpacing(12)
        header=QHBoxLayout();title=QLabel('剪');title.setObjectName('title');header.addWidget(title);header.addStretch()
        self.import_recording=QPushButton('导入最近录屏');self.import_recording.setEnabled(False);header.addWidget(self.import_recording)
        self.load_button=self.button('添加素材…',self.choose_video);header.addWidget(self.load_button);outer.addLayout(header)
        self.metadata=QLabel('');self.metadata.setObjectName('muted');self.metadata.setWordWrap(True);self.metadata.hide()
        self.input_path=QLineEdit();self.input_path.hide()
        self.library_panel,bin_layout=self.card('素材库')
        heading=bin_layout.takeAt(0).widget();bin_header=QHBoxLayout();bin_header.addWidget(heading);bin_header.addStretch()
        bin_header.addWidget(self.button('加入时间线',self.add_selected_to_project))
        self.media_library=MediaLibrary(self.ffmpeg,self.ffprobe,self)
        bin_header.addWidget(self.button('移出素材库',self.media_library.remove_selected));bin_layout.addLayout(bin_header)
        self.media_library.setMinimumHeight(98);bin_layout.addWidget(self.media_library)
        self.library_panel.setMaximumHeight(175);outer.addWidget(self.library_panel)
        self.media_library.empty_text='添加素材后，拖到预览或时间线；多选可连续加入项目'
        self.media_library.itemDoubleClicked.connect(self.library_preview);self.media_library.files_dropped.connect(self.import_files)
        self.media_library.changed.connect(self.library_changed);self.media_library.metadata_ready.connect(self.drain_additions)
        self.media_library.problem.connect(lambda message:self.logs.append('素材库：'+message))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);outer.addWidget(scroll,1)
        self.edit_controls=QWidget();content=QVBoxLayout(self.edit_controls);content.setContentsMargins(0,0,0,0);content.setSpacing(12)
        scroll.setWidget(self.edit_controls)
        self.preview_card,preview_layout=self.card('项目预览与时间线');content.addWidget(self.preview_card)
        preview_row=QHBoxLayout();self.video_canvas=VideoCanvas();self.video_canvas.max_preview_height=350
        self.video_canvas.files_dropped.connect(self.preview_files);preview_row.addWidget(self.video_canvas,1)
        save,save_layout=self.card('导出项目');save.setFixedWidth(300);save_layout.setContentsMargins(12,8,12,10);save_layout.setSpacing(6)
        save.setStyleSheet('QLineEdit,QComboBox {padding:5px 8px;min-height:18px;} QPushButton {padding:6px 10px;} QPushButton#export {padding:8px 12px;}')
        preview_row.addWidget(save,0,Qt.AlignTop)
        self.output_name=QLineEdit('输出视频');self.output_name.setPlaceholderText('视频名称')
        self.output_name.textEdited.connect(lambda *_:setattr(self,'output_name_custom',True));save_layout.addWidget(self.output_name)
        self.output_directory=QLineEdit(self.import_directory());save_layout.addWidget(self.output_directory)
        save_layout.addWidget(self.button('选择输出目录…',self.choose_directory))
        self.export_quality=QComboBox();self.export_quality.setToolTip('导出清晰度与实际输出分辨率')
        for text,crf in [('高清',18),('标准',23),('省空间',28)]:self.export_quality.addItem(text,crf)
        self.export_quality.setCurrentIndex(1);save_layout.addWidget(self.export_quality)
        self.export_quality.currentIndexChanged.connect(self.update_project_controls)
        self.keep_audio=QCheckBox('保留视频原声');self.keep_audio.setChecked(True);self.keep_audio.toggled.connect(lambda value:self.player.setMuted(not value));save_layout.addWidget(self.keep_audio)
        self.plan_label=QLabel('');self.plan_label.setWordWrap(True);self.plan_label.setObjectName('muted');save_layout.addWidget(self.plan_label)
        self.export_button=self.button('导出完整项目',self.start_export);self.export_button.setObjectName('export');save_layout.addWidget(self.export_button)
        preview_layout.addLayout(preview_row)
        self.preview_status=QLabel('');self.preview_status.setObjectName('muted');self.preview_status.hide();preview_layout.addWidget(self.preview_status)
        self.timeline=ProjectTimeline(self.project);self.timeline.thumbnail_lookup=lambda key:self.media_library.items.get(key);preview_layout.addWidget(self.timeline)
        self.timeline.seek_requested.connect(self.seek);self.timeline.move_requested.connect(self.move_clip)
        self.timeline.files_dropped.connect(self.add_to_project);self.timeline.audio_files_dropped.connect(lambda paths,frame:self.add_to_project(paths,audio_frame=frame));self.timeline.selection_changed.connect(self.selection_changed)
        self.timeline.delete_requested.connect(self.delete_selection);self.timeline.undo_requested.connect(self.undo_project)
        self.timeline.clip_selected.connect(self.clip_selected);self.timeline.clip_delete_requested.connect(self.delete_clip)
        self.timeline.clip_speed_requested.connect(self.set_clip_speed)
        self.position_label=QLabel('00:00:00.000 / 00:00:00.000');self.position_label.setObjectName('muted');self.position_label.setWordWrap(True)
        preview_layout.addWidget(self.position_label)
        transport=QHBoxLayout();self.previous=self.button('◀ 5 秒',lambda:self.jump_seconds(-5))
        self.play_button=self.button('▶ 播放',self.toggle_play);self.next=self.button('5 秒 ▶',lambda:self.jump_seconds(5))
        for button in (self.previous,self.play_button,self.next):transport.addWidget(button)
        transport.addWidget(QLabel('项目倍速'));self.speed=QComboBox()
        for factor in (.25,.5,.75,1,1.25,1.5,2,3,4):self.speed.addItem(f'{factor:g} ×',factor)
        self.speed.addItem('自定义',None);self.speed.setCurrentIndex(3);self.speed.currentIndexChanged.connect(self.speed_changed)
        transport.addWidget(self.speed);self.custom_speed=QDoubleSpinBox();self.custom_speed.setRange(.1,16);self.custom_speed.setValue(1)
        self.custom_speed.setSuffix(' ×');self.custom_speed.valueChanged.connect(self.speed_changed);self.custom_speed.hide();transport.addWidget(self.custom_speed)
        transport.addStretch();self.undo_button=self.button('撤销',self.undo_project);self.redo_button=self.button('重做',self.redo_project)
        transport.addWidget(self.undo_button);transport.addWidget(self.redo_button);transport.addWidget(self.button('清空项目',self.clear_project))
        preview_layout.addLayout(transport)
        zoom_row=QHBoxLayout();self.selection_label=QLabel('');self.selection_label.setObjectName('muted');zoom_row.addWidget(self.selection_label,1)
        zoom_row.addWidget(self.button('−',lambda:self.timeline.set_zoom(self.timeline.zoom*.8)))
        zoom_row.addWidget(self.button('+',lambda:self.timeline.set_zoom(self.timeline.zoom*1.25)))
        zoom_row.addWidget(self.button('适合窗口',self.timeline.fit));preview_layout.addLayout(zoom_row);content.addStretch()
        footer,footer_layout=self.card('导出状态');outer.addWidget(footer)
        row=QHBoxLayout();self.export_status=QLabel('准备就绪');self.export_status.setWordWrap(True);row.addWidget(self.export_status,1)
        self.cancel_button=self.button('取消导出',self.cancel_export);self.cancel_button.setEnabled(False);row.addWidget(self.cancel_button)
        self.open_export=self.button('打开成片',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_export))))
        self.open_export.setEnabled(False);row.addWidget(self.open_export);row.addWidget(self.button('输出目录',self.open_directory))
        self.log_button=QPushButton('日志 ▾');self.log_button.setCheckable(True);row.addWidget(self.log_button);footer_layout.addLayout(row)
        self.export_progress=QProgressBar();self.export_progress.setRange(0,100);self.export_progress.setValue(0);footer_layout.addWidget(self.export_progress)
        self.logs=QTextEdit();self.logs.setReadOnly(True);self.logs.setMaximumHeight(100);self.logs.document().setMaximumBlockCount(150)
        self.logs.hide();footer_layout.addWidget(self.logs);self.log_button.toggled.connect(self.logs.setVisible)

    def import_directory(self):
        fallback=Path(str(self.settings.value('directory',Path.home()/'ffmpeg_screen_recorder'/'video'))).expanduser()
        saved=Path(str(self.settings.value('editor/import_directory',fallback))).expanduser()
        return str(saved if saved.is_dir() else fallback if fallback.is_dir() else Path.home())
    def remember_directory(self,path):self.settings.setValue('editor/import_directory',str(Path(path).expanduser().resolve().parent));self.settings.sync()
    def choose_video(self):
        paths,_=QFileDialog.getOpenFileNames(self,'添加素材',self.import_directory(),'视频与音频 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mp3 *.wav *.flac *.ogg *.m4a *.aac *.aiff *.wma *.opus);;所有文件 (*)')
        if paths:self.import_files(paths)
    def restore_library(self):
        try:paths=json.loads(str(self.settings.value('editor/library_json','[]')))
        except (ValueError,TypeError):paths=[]
        if isinstance(paths,list):self.media_library.add_files([p for p in paths if isinstance(p,str)])
    def library_changed(self):
        self.settings.setValue('editor/library_json',json.dumps(self.media_library.paths(),ensure_ascii=False));self.settings.sync()
        self.pending_additions=[entry for entry in self.pending_additions if all(path in self.media_library.items for path in entry[0])]
    def import_files(self,paths):
        if self.busy:return
        valid=[str(Path(p).expanduser().resolve()) for p in paths if Path(p).expanduser().is_file()]
        if valid:self.remember_directory(valid[-1]);self.media_library.add_files(valid)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not self.busy:event.acceptProposedAction()
    def dropEvent(self,event):self.import_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
    def preview_files(self,paths):self.add_to_project(paths)
    def load_video(self,path):self.add_to_project([str(path)])
    def library_preview(self,item):
        path=item.data(Qt.UserRole)
        existing=next((i for i,c in enumerate(self.project.clips) if str(c.info.path)==path),None)
        audio=next((c for c in self.project.audio_clips if str(c.info.path)==path),None)
        if existing is not None:self.seek(self.project.offset(existing))
        elif audio:self.seek(audio.offset)
        else:self.add_to_project([path])
    def add_selected_to_project(self):self.add_to_project(self.media_library.selected_paths())

    def add_to_project(self,paths,insertion=-1,audio_frame=None):
        if self.busy or not paths:return
        valid=[str(Path(p).expanduser().resolve()) for p in paths if Path(p).expanduser().is_file()]
        if not valid:return
        new=[p for p in valid if p not in self.media_library.items]
        if new:self.import_files(new)
        anchor=self.project.clips[insertion].uid if 0<=insertion<len(self.project.clips) else None
        frame=self.timeline.drop_frame if self.timeline.drop_frame is not None else self.current_frame
        self.pending_additions.append((valid,anchor,frame if audio_frame is None else audio_frame));self.drain_additions()
    def drain_additions(self):
        if self.busy:return
        self.timeline.update()
        while self.pending_additions:
            paths,anchor,audio_frame=self.pending_additions[0]
            if any(p in self.media_library.failures for p in paths):
                self.pending_additions.pop(0);self.notify('素材读取失败，请从素材库移除并重新选择。');continue
            if not all(p in self.media_library.infos for p in paths):return
            self.pending_additions.pop(0)
            insertion=next((i for i,c in enumerate(self.project.clips) if c.uid==anchor),len(self.project.clips))
            infos=[self.media_library.infos[p] for p in paths]
            video=[info for info in infos if getattr(info,'has_video',True)];audio=[info for info in infos if not getattr(info,'has_video',True)]
            was_empty=not self.project.frames
            clips=self.project.insert(video,insertion) if video else []
            sounds=self.project.insert_audio(audio,audio_frame) if audio else []
            if clips and sounds:self.project.history.pop()
            if not self.output_name_custom:self.output_name.setText((self.project.clips or self.project.audio_clips)[0].info.path.stem+'_项目')
            if was_empty:self.output_directory.setText(str(infos[0].path.parent))
            self.project_changed(self.project.offset(insertion) if clips else sounds[0].offset);self.video_loaded.emit()

    def project_changed(self,frame=None):
        self.audio_preview.prune();self.timeline.clear_selection();self.timeline.refresh();self.update_project_controls()
        if self.project.frames:
            self.video_canvas.fixed_aspect=(self.project.width or 1920)/(self.project.height or 1080)
            self.video_canvas.set_aspect(self.project.width or 1920,self.project.height or 1080)
            self.seek(self.current_frame if frame is None else frame)
        else:
            self.wanted_play=False;self.media_seek_pending=False;self._switching=False;self.active_index=None;self.info=None;self.current_source=None
            self.player.stop();self.player.setMedia(QMediaContent());self.preview_path=None;self.current_frame=0
            self.thumbnail_serial+=1;self.thumbnail_timer.stop();self.video_canvas.clear('将素材拖入时间线');self.show_position()
    def update_project_controls(self,*_):
        labels=[('高清',18),('标准',23),('省空间',28)]
        for index,(name,quality) in enumerate(labels):
            if self.project.frames:
                w,h=export_size(self.project.width or 1920,self.project.height or 1080,quality);label=f'{name} · {w} × {h}'
            else:label=name+' · '+{18:'原分辨率',23:'最高 1080p',28:'最高 720p'}[quality]
            self.export_quality.setItemText(index,label)
        enabled=bool(self.project.frames) and not self.busy
        for control in (self.previous,self.play_button,self.next,self.speed,self.custom_speed,self.export_button):control.setEnabled(enabled)
        self.undo_button.setEnabled(bool(self.project.history) and not self.busy);self.redo_button.setEnabled(bool(self.project.future) and not self.busy)
        self.timeline.undo_enabled=bool(self.project.history)
        if self.project.fps:
            duration=self.project.duration/self.speed_value()
            self.metadata.setText(f'项目 · {len(self.project.clips)} 个片段 · {self.project.frames} 帧 · {clock(self.project.duration)} · {self.project.width} × {self.project.height} · {float(self.project.fps):g} 帧/秒')
            w,h=export_size(self.project.width or 1920,self.project.height or 1080,self.export_quality.currentData())
            self.plan_label.setText(f'输出 {w} × {h} · {self.speed_value():g}× · {duration:.2f} 秒')
        else:self.metadata.setText('');self.plan_label.setText('')
    def move_clip(self,uid,insertion):
        if self.busy:return
        audio=next((c for c in self.project.audio_clips if c.uid==uid),None)
        if audio:
            if self.project.move_audio(uid,insertion):self.project_changed(insertion);self.timeline.select_clip(uid)
        elif self.project.move(uid,insertion):
            index=next(i for i,c in enumerate(self.project.clips) if c.uid==uid);self.project_changed(self.project.offset(index))
    def selection_changed(self,selection):
        if selection and self.project.fps:
            a,b=selection;self.selection_label.setText(f'选中 {clock(a/float(self.project.fps))} 至 {clock(b/float(self.project.fps))} · {b-a} 帧')
        else:self.selection_label.setText('')
    def delete_selection(self):
        if self.busy or not self.timeline.selection:return
        a,b=self.timeline.selection
        if self.project.delete_clip_range(self.timeline.selection_uid,a,b):self.project_changed(min(a,max(0,self.project.frames-1)))
    def clip_selected(self,uid):
        clip=self.project.get_clip(uid)
        if clip:self.selection_label.setText(f'选中片段 · {clip.info.path.name} · {clip.speed:g} × · {clock(clip.frames/float(self.project.fps))}')
        elif not self.timeline.selection:self.selection_label.setText('')
    def jump_seconds(self,seconds):
        if self.project.frames and not self.busy:self.seek(self.current_frame+round(seconds*float(self.project.fps)))
    def delete_selected_clip(self):
        focus=QApplication.focusWidget()
        if focus is self.media_library or self.media_library.isAncestorOf(focus):self.media_library.remove_selected()
        elif self.timeline.selected_uid:self.delete_clip(self.timeline.selected_uid)
    def delete_clip(self,uid):
        if self.busy:return
        clip=self.project.get_clip(uid)
        if clip and self.project.delete_clip(uid):self.project_changed(min(self.current_frame,max(0,self.project.frames-1)))
    def set_clip_speed(self,uid,speed):
        if self.busy:return
        if self.project.set_clip_speed(uid,speed):
            clip=self.project.get_clip(uid)
            frame=clip.offset if clip in self.project.audio_clips else self.project.offset(next(i for i,c in enumerate(self.project.clips) if c.uid==uid))
            self.project_changed(frame);self.timeline.select_clip(uid)
    def undo_project(self):
        if not self.busy and self.project.undo():self.project_changed()
    def redo_project(self):
        if not self.busy and self.project.redo():self.project_changed()
    def clear_project(self):
        if not self.busy and self.project.clear():self.project_changed(0)
    def speed_value(self):return self.speed.currentData() if self.speed.currentData() is not None else self.custom_speed.value()
    def speed_changed(self,*_):
        self._clock_frame=self.current_frame;self._clock_at=time.monotonic()
        self.custom_speed.setVisible(self.speed.currentData() is None);self.player.setPlaybackRate(self.playback_rate());self.update_project_controls()

    def playback_rate(self):
        clip=self.project.clips[self.active_index] if self.active_index is not None and self.active_index<len(self.project.clips) else None
        return self.speed_value()*(clip.speed if clip else 1)
    def ensure_playing(self):
        if not self.wanted_play or self._switching or self.media_seek_pending or self._advance_pending or self._tail_mode or not self.project.clips:return
        status=self.player.mediaStatus()
        if status==QMediaPlayer.EndOfMedia:self.advance_clip()
        elif status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia,QMediaPlayer.StalledMedia) and self.player.state()!=QMediaPlayer.PlayingState:
            self.player.setPlaybackRate(self.playback_rate());self.player.play()
    def queue_resume(self):
        generation=self._playback_generation
        QTimer.singleShot(0,lambda:self.ensure_playing() if generation==self._playback_generation else None)
    def seek(self,frame):
        if not self.project.frames:return
        self.show_frame(frame,False)
    def show_frame(self,frame,play,keep_clock=False):
        if not self.project.frames:return
        frame=max(0,min(self.project.frames-1,int(frame)))
        if not keep_clock:self._clock_frame=frame;self._clock_at=time.monotonic()
        self._tail_mode=not self.project.clips or frame>=self.project.video_frames
        found=self.project.locate(frame)
        if self._tail_mode:
            self._playback_generation+=1;self._advance_pending=False;self.wanted_play=play;self.current_frame=frame
            self._switching=False;self.media_seek_pending=False;self.player.pause()
            if not found:self.active_index=None;self.info=None;self.video_canvas.clear('音频预览')
            else:self.thumbnail_serial+=1;self.thumbnail_timer.start()
            self.play_button.setText('Ⅱ 暂停' if play else '▶ 播放');self.show_position();self.sync_audio(True);return
        index,clip,source_frame,offset=found
        self._playback_generation+=1;self._advance_pending=False
        self._switching=True;self.wanted_play=play;self.current_frame=max(0,min(self.project.frames-1,int(frame)))
        self.active_index=index;self.info=clip.info;self.current_source=clip.info.path;self.input_path.setText(str(clip.info.path))
        self.thumbnail_serial+=1;self.thumbnail_timer.stop()
        source_position=clip.source_position(self.current_frame-offset)
        self._source_position=math.ceil(source_position/float(self.project.fps)*1000-1e-9);self._seek_gate=source_position
        path=self.preview_sources.get(str(clip.info.path),clip.info.path)
        changed=Path(path)!=self.preview_path or self.player.mediaStatus()==QMediaPlayer.InvalidMedia
        if changed:
            self.preview_path=Path(path);self.media_seek_pending=True;self._expected_epoch=self.surface.epoch+1
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(path))))
            self.player.pause()
        elif self.media_seek_pending or self.player.mediaStatus()==QMediaPlayer.LoadingMedia:
            self.media_seek_pending=True;self._switching=True;self.player.pause()
        else:
            self.media_seek_pending=False;self._expected_epoch=self.surface.epoch
            self.player.setPosition(self._source_position);self.player.setPlaybackRate(self.playback_rate())
            self.player.play() if play else self.player.pause();self._switching=False
        self.play_button.setText('Ⅱ 暂停' if play else '▶ 播放');self.show_position()
        if not play:self.thumbnail_timer.start()
        else:self.queue_resume()
        key=str(clip.info.path)
        if key not in self.preview_sources and self._proxy_requested!=key:
            self._proxy_requested=key;self.proxy.prepare(clip.info)
    def sync_audio(self,force=False):
        if self.project.fps:
            self.audio_preview.muted=self.test_mode;self.audio_preview.sync(self.current_frame,self.wanted_play,self.speed_value(),self.project.fps,force)
    def tick_tracks(self):
        if not self.project.audio_clips:return
        if self.wanted_play:
            frame=self._clock_frame+int((time.monotonic()-self._clock_at)*float(self.project.fps)*self.speed_value())
            if frame>=self.project.frames:self.seek(self.project.frames-1);return
            found=self.project.locate(frame)
            tail=not found or frame>=self.project.video_frames
            if tail:
                if not self._tail_mode:self.show_frame(frame,True,True)
                self.current_frame=frame
            elif found[0]!=self.active_index or self._tail_mode:
                self.show_frame(frame,True,True)
            else:
                self.current_frame=frame
                if not self.media_seek_pending and not self._switching:
                    ms=math.ceil(found[1].source_position(frame-found[3])/float(self.project.fps)*1000-1e-9)
                    if abs(self.player.position()-ms)>220:self.player.setPosition(ms)
                    self.ensure_playing()
            self.show_position()
        self.sync_audio()
    def media_status_changed(self,status):
        if status==QMediaPlayer.LoadingMedia:
            self.media_seek_pending=True;self._switching=True
        elif status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia) and self.media_seek_pending:
            self.media_seek_pending=False
            if self.project.audio_clips:
                found=self.project.locate(self.current_frame)
                if found and found[0]==self.active_index:
                    position=found[1].source_position(self.current_frame-found[3]);self._source_position=math.ceil(position/float(self.project.fps)*1000-1e-9);self._seek_gate=position
            self.player.setPosition(self._source_position);self.player.setPlaybackRate(self.playback_rate())
            self.media_seek_pending=False;self._switching=False
            if self.wanted_play:self.queue_resume()
        elif status==QMediaPlayer.EndOfMedia and self.wanted_play and not self._switching:self.advance_clip()
    def toggle_play(self):
        if not self.project.frames:return
        if self.wanted_play:self.seek(self.current_frame)
        else:self.show_frame(0 if self.current_frame>=self.project.frames-1 else self.current_frame,True)
    def play_state_changed(self,state):
        self.play_button.setText('Ⅱ 暂停' if self.wanted_play else '▶ 播放')
        if self.wanted_play and state!=QMediaPlayer.PlayingState:self.queue_resume()
    def advance_clip(self):
        if self.project.audio_clips:return
        if self._advance_pending or not self.wanted_play or self.active_index is None:return
        self._advance_pending=True;generation=self._playback_generation;uid=self.project.clips[self.active_index].uid
        # Let the old backend finish EOS/stop before loading and playing its successor.
        def advance():
            if generation!=self._playback_generation:return
            self._advance_pending=False
            if not self.wanted_play or self.active_index is None or self.project.clips[self.active_index].uid!=uid:return
            if self.active_index+1<len(self.project.clips):self.show_frame(self.project.offset(self.active_index+1),True)
            else:self.seek(self.project.frames-1)
        QTimer.singleShot(0,advance)
    def position_changed(self,ms):
        if self.project.audio_clips:return
        if not self.wanted_play or self._switching or self.media_seek_pending or self.active_index is None or self._advance_pending:return
        clip=self.project.clips[self.active_index];frame=ms/1000*float(self.project.fps)
        if self._seek_gate is not None and abs(frame-self._seek_gate)>max(3,round(float(self.project.fps))):return
        local=clip.timeline_frame(frame)
        if local>=clip.frames-.01:self.advance_clip();return
        if clip.info.fps!=self.project.fps or clip.speed!=1 or not self._has_frame_timestamps:
            self.current_frame=self.project.offset(self.active_index)+max(0,min(clip.frames-1,math.floor(local+1e-7)));self.show_position()
    def video_frame_ready(self,image,context):
        if not self.wanted_play or self._switching or self.media_seek_pending or self.active_index is None or self._advance_pending:return
        microseconds,epoch=context
        if epoch<self._expected_epoch:return
        clip=self.project.clips[self.active_index];fps=float(self.project.fps)
        self._has_frame_timestamps=microseconds>=0
        frame=round(microseconds/1e6*fps) if microseconds>=0 and clip.info.fps==self.project.fps else self.player.position()/1000*fps
        if self._seek_gate is not None:
            if abs(frame-self._seek_gate)>max(3,round(fps)):return
            self._seek_gate=None
        local=clip.timeline_frame(frame)
        if local<-.01:return
        if local>=clip.frames-.01:self.advance_clip();return
        if not self.project.audio_clips:self.current_frame=self.project.offset(self.active_index)+max(0,min(clip.frames-1,math.floor(local+1e-7)))
        self.video_canvas.set_image(image);self.show_position()
    def show_position(self):
        self.timeline.cursor=self.current_frame;self.timeline.update()
        if self.project.fps:
            clip=self.project.locate(self.current_frame)
            self.position_label.setText(f'{clock(self.current_frame/float(self.project.fps))} / {clock(self.project.duration)} · 第 {self.current_frame+1} / {self.project.frames} 帧'+(f' · 片段 {clip[0]+1}/{len(self.project.clips)} · {clip[1].info.path.name}' if clip else ''))
        else:self.position_label.setText('00:00:00.000 / 00:00:00.000')
    def request_thumbnail(self):
        found=self.project.locate(self.current_frame)
        if not found or not self.ffmpeg or (self.wanted_play and not self._tail_mode):return
        index,clip,frame,offset=found;fps=float(self.project.fps);early=max(0,frame-round(fps))
        self.thumbnail_serial+=1;serial=self.thumbnail_serial
        if self.thumbnail_process and self.thumbnail_process.state()!=QProcess.NotRunning:self.thumbnail_process.kill()
        process=QProcess(self);process.setProcessEnvironment(clean_child_environment());self.thumbnail_process=process
        process.finished.connect(lambda code,status:self.thumbnail_ready(process,serial,code))
        rate=f'{self.project.fps.numerator}/{self.project.fps.denominator}'
        process.start(self.ffmpeg,['-v','error','-threads','2','-ss',f'{early/fps:.9f}','-i',str(clip.info.path),'-frames:v','1',
            '-vf',f'fps={rate}:start_time=0,select=eq(n\\,{frame-early}),scale=min(960\\,iw):-2',
            '-threads','1','-f','image2pipe','-c:v','png','pipe:1'])
    def thumbnail_ready(self,process,serial,code):
        from PyQt5.QtGui import QImage
        data=bytes(process.readAllStandardOutput());process.deleteLater()
        if process is self.thumbnail_process:self.thumbnail_process=None
        if serial==self.thumbnail_serial and code==0 and (not self.wanted_play or self._tail_mode):
            image=QImage.fromData(data)
            if not image.isNull():self.video_canvas.set_image(image)
    def proxy_progress(self,percent):self.preview_status.setText(f'正在准备当前片段预览 · {percent}%');self.preview_status.show()
    def proxy_ready(self,source,path):
        self.preview_sources[str(source)]=Path(path)
        if self.current_source==source:
            self.preview_status.setText('流畅项目预览');self.preview_status.show();self.show_frame(self.current_frame,self.wanted_play)
    def proxy_error(self,message):self.preview_status.setText('使用原素材预览');self.logs.append('预览：'+message)
    def media_error(self,*_):
        if self.player.error():self.logs.append('预览：'+self.player.errorString())

    def notify(self,message):
        self.export_status.setText(message);self.logs.append(message)
        if not self.test_mode:QMessageBox.warning(self,'神录剪',message)
    def choose_directory(self):
        path=QFileDialog.getExistingDirectory(self,'选择导出目录',self.output_directory.text())
        if path:self.output_directory.setText(path)
    def open_directory(self):
        path=Path(self.output_directory.text()).expanduser()
        if path.is_dir():QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def start_export(self):
        if self.busy or not self.project.frames:return
        if not self.ffmpeg:self.notify('未找到 ffmpeg。');return
        try:
            destination=output_path(self.output_directory.text(),self.output_name.text(),False);destination.parent.mkdir(parents=True,exist_ok=True)
            pending=destination.parent/f'.{destination.stem}.export-{uuid.uuid4().hex}.mp4'
            arguments,duration=project_export_arguments(self.project,pending,self.speed_value(),self.export_quality.currentData(),self.keep_audio.isChecked())
        except (ValueError,OSError) as error:self.notify(str(error));return
        self.wanted_play=False;self.player.pause();self.audio_preview.stop();self.busy=True;self.cancelled=False;self.result_path=destination;self.pending_path=pending
        self.expected_duration=duration;self.error_tail='';self.progress_buffer=''
        self.edit_controls.setEnabled(False);self.library_panel.setEnabled(False);self.load_button.setEnabled(False)
        self.export_button.setEnabled(False);self.cancel_button.setEnabled(True);self.export_progress.setValue(0);self.open_export.setEnabled(False)
        w,h=export_size(self.project.width or 1920,self.project.height or 1080,self.export_quality.currentData())
        self.export_status.setText(f'正在导出完整项目 · {w} × {h}…');self.logs.clear();self.encoder.start(self.ffmpeg,arguments)
    def read_errors(self):
        text=bytes(self.encoder.readAllStandardError()).decode(errors='replace');self.error_tail=(self.error_tail+text)[-5000:]
        if text.strip():self.logs.append(text.strip())
    def read_progress(self):
        self.progress_buffer+=bytes(self.encoder.readAllStandardOutput()).decode(errors='replace')
        while '\n' in self.progress_buffer:
            line,self.progress_buffer=self.progress_buffer.split('\n',1)
            if line.startswith('out_time_us='):
                try:progress=int(float(line.split('=',1)[1])/1e6/max(self.expected_duration,.001)*100)
                except ValueError:continue
                self.export_progress.setValue(min(99,max(0,progress)))
    def cancel_export(self):
        if self.busy:
            self.cancelled=True;self.export_status.setText('正在取消…');self.cancel_button.setEnabled(False)
            self.encoder.write(b'q\n');self.encoder.closeWriteChannel()
    def encoding_error(self,error):
        if error==QProcess.FailedToStart:self.encoding_finished(1,QProcess.CrashExit)
    def encoding_finished(self,code,status):
        if not self.busy:return
        self.read_errors();self.read_progress();self.busy=False;self.edit_controls.setEnabled(True);self.library_panel.setEnabled(True)
        self.load_button.setEnabled(True);self.cancel_button.setEnabled(False)
        success=not self.cancelled and code==0 and status==QProcess.NormalExit and self.pending_path and self.pending_path.is_file() and self.pending_path.stat().st_size>0
        if success:
            try:
                for _ in range(1000):
                    try:os.link(self.pending_path,self.result_path);break
                    except FileExistsError:self.result_path=output_path(str(self.result_path.parent),self.output_name.text(),False)
                else:raise OSError('无法分配新的导出文件名。')
                self.pending_path.unlink();self.last_export=self.result_path;self.export_progress.setValue(100)
                self.export_status.setText('✓ 已导出：'+str(self.last_export));self.open_export.setEnabled(True)
            except OSError as error:success=False;self.notify(f'视频已生成，但保存失败：{error}\n临时视频：{self.pending_path}')
        elif self.cancelled:
            if self.pending_path:self.pending_path.unlink(missing_ok=True)
            self.export_status.setText('已取消导出')
        else:
            if self.pending_path:self.pending_path.unlink(missing_ok=True)
            self.notify(self.error_tail.strip() or '视频导出失败。')
        self.update_project_controls();self.drain_additions();self.export_finished.emit(bool(success),str(self.last_export if success else ''))
    def shutdown_preview(self):
        self.wanted_play=False;self._playback_generation+=1;self.playback_timer.stop();self.track_timer.stop();self.audio_preview.shutdown();self.thumbnail_serial+=1;self.pending_additions.clear();self.media_library.shutdown();self.proxy.stop()
        self.player.stop();self.player.setMedia(QMediaContent());self.thumbnail_timer.stop()
        if self.thumbnail_process and self.thumbnail_process.state()!=QProcess.NotRunning:self.thumbnail_process.kill();self.thumbnail_process.waitForFinished(1000)
        if self.proxy.process.state()!=QProcess.NotRunning:self.proxy.process.waitForFinished(1000)
