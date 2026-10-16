"""A draggable library of video and audio assets."""
import json
from pathlib import Path

from PyQt5.QtCore import QMimeData,QProcess,QSize,Qt,QUrl,pyqtSignal
from PyQt5.QtGui import QIcon,QPainter,QColor,QPixmap
from PyQt5.QtWidgets import QAbstractItemView,QListView,QListWidget,QListWidgetItem,QStyle
from app.media.info import probe_media
from app.common.environment import clean_child_environment


class VideoList(QListWidget):
    files_dropped=pyqtSignal(object)
    def mimeData(self,items):
        mime=super().mimeData(items)
        mime.setUrls([QUrl.fromLocalFile(item.data(Qt.UserRole)) for item in items])
        return mime

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
        else:super().dragEnterEvent(event)

    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
        else:super().dragMoveEvent(event)

    def paintEvent(self,event):
        super().paintEvent(event)
        if self.count()==0:
            painter=QPainter(self.viewport());painter.setPen(QColor('#8da1b9'))
            painter.drawText(self.viewport().rect().adjusted(8,4,-8,-4),Qt.AlignCenter|Qt.TextWordWrap,self.empty_text)


class MediaLibrary(VideoList):
    changed=pyqtSignal()
    metadata_ready=pyqtSignal()
    problem=pyqtSignal(str)
    def __init__(self,ffmpeg,ffprobe,parent=None):
        super().__init__(parent)
        self.ffmpeg=ffmpeg;self.ffprobe=ffprobe;self.infos={};self.failures={};self.items={};self.jobs=[];self.active=None;self.stopped=False
        self.empty_text='添加视频或音频到素材库，再拖入时间线'
        self.setViewMode(QListView.IconMode);self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static);self.setIconSize(QSize(120,68));self.setGridSize(QSize(150,104))
        self.setSpacing(4);self.setWordWrap(True);self.setMinimumHeight(110)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop);self.setDefaultDropAction(Qt.CopyAction)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.process=QProcess(self);self.process.setProcessEnvironment(clean_child_environment())
        self.process.finished.connect(self.job_finished);self.process.errorOccurred.connect(self.job_error)
        self.phase='probe'

    def paths(self):return [self.item(i).data(Qt.UserRole) for i in range(self.count())]
    def selected_paths(self):return [item.data(Qt.UserRole) for item in self.selectedItems()]

    def add_files(self,paths):
        added=[]
        for value in paths:
            path=Path(value).expanduser().resolve();key=str(path)
            if not path.is_file() or key in self.items:continue
            item=QListWidgetItem(self.style().standardIcon(QStyle.SP_MediaPlay),path.name)
            item.setData(Qt.UserRole,key);item.setToolTip(key+'\n正在读取…')
            self.infos.pop(key,None);self.failures.pop(key,None)
            self.addItem(item);self.items[key]=item;self.jobs.append(key);added.append(key)
        if added:self.changed.emit();self.next_job()
        return added

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Delete and event.modifiers()==Qt.NoModifier:
            self.remove_selected();event.accept();return
        super().keyPressEvent(event)

    def remove_selected(self):
        for item in self.selectedItems():
            key=item.data(Qt.UserRole);self.items.pop(key,None);self.takeItem(self.row(item))
        self.changed.emit()

    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:self.files_dropped.emit(paths);event.setDropAction(Qt.CopyAction);event.accept()

    def next_job(self):
        if self.stopped or self.process.state()!=QProcess.NotRunning or self.active:return
        while self.jobs:
            self.active=self.jobs.pop(0)
            if self.active not in self.items:self.active=None;continue
            self.phase='probe'
            if not self.ffprobe:self.problem.emit('未找到 ffprobe。');self.active=None;return
            self.process.start(self.ffprobe,['-v','error','-show_streams','-show_format','-of','json',self.active]);return

    def job_error(self,error):
        if error==QProcess.FailedToStart:self.job_finished(1,QProcess.CrashExit)

    def job_finished(self,code,status):
        key=self.active;data=bytes(self.process.readAllStandardOutput())
        errors=bytes(self.process.readAllStandardError()).decode(errors='replace')
        if self.stopped:return
        if key in self.items and self.phase=='probe':
            try:
                if code or status!=QProcess.NormalExit:raise ValueError(errors.strip() or '素材读取失败')
                info=probe_media(Path(key),json.loads(data));self.infos[key]=info
                item=self.items[key]
                item.setToolTip(f'{key}\n'+(f'音频 · {info.duration:.2f} 秒' if not getattr(info,'has_video',True) else f'{info.width} × {info.height} · {float(info.fps):g} 帧/秒 · {info.duration:.2f} 秒'))
                self.metadata_ready.emit()
                if self.ffmpeg:
                    self.phase='thumbnail'
                    if not getattr(info,'has_video',True):
                        self.process.start(self.ffmpeg,['-v','error','-threads','2','-i',key,'-filter_complex','[0:a:0]showwavespic=s=120x68:colors=0x7ac7ae','-frames:v','1','-threads','1','-f','image2pipe','-c:v','png','pipe:1']);return
                    self.process.start(self.ffmpeg,['-v','error','-threads','2','-ss',str(min(.5,info.duration/2)),
                        '-i',key,'-frames:v','1','-vf','scale=120:68:force_original_aspect_ratio=decrease',
                        '-threads','1','-f','image2pipe','-c:v','png','pipe:1']);return
            except (ValueError,KeyError,TypeError) as error:
                self.failures[key]=str(error)
                self.items[key].setToolTip(key+'\n'+str(error));self.problem.emit(Path(key).name+'：'+str(error))
                self.metadata_ready.emit()
        elif key in self.items and self.phase=='thumbnail' and code==0:
            pixmap=QPixmap()
            if pixmap.loadFromData(data):self.items[key].setIcon(QIcon(pixmap));self.metadata_ready.emit()
        self.active=None;self.next_job()

    def shutdown(self):
        self.stopped=True;self.jobs.clear()
        if self.process.state()!=QProcess.NotRunning:self.process.kill();self.process.waitForFinished(1000)

