"""Aspect-fitted CPU video rendering and optional lightweight preview copies."""
import hashlib
import uuid
from pathlib import Path

from PyQt5.QtCore import QProcess, QStandardPaths, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtMultimedia import QAbstractVideoBuffer, QAbstractVideoSurface, QVideoFrame
from PyQt5.QtWidgets import QSizePolicy, QWidget


class VideoCanvas(QWidget):
    files_dropped=pyqtSignal(object)
    """Shrink-wrap the video itself; no fixed-height letterboxing canvas."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.image=QImage();self.message='将素材拖入预览或时间线'
        self.aspect=16/9;self.fixed_aspect=None;self.max_preview_height=480;self.painted_rect=None;self._sizing=False
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.setMinimumHeight(2)
        self.setAcceptDrops(True)

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:self.files_dropped.emit(paths);event.setDropAction(Qt.CopyAction);event.accept()

    def set_aspect(self,width,height):
        if width>0 and height>0:
            ratio=width/height
            if abs(ratio-self.aspect)>.001:
                self.aspect=ratio;self.update_size()

    def update_size(self):
        if self._sizing:return
        self._sizing=True
        # Portrait and very tall videos fit without making the whole editor taller.
        height=max(2,min(self.max_preview_height,round(max(2,self.width())/self.aspect)))
        if self.height()!=height:self.setFixedHeight(height)
        self._sizing=False;self.update()

    def resizeEvent(self,event):
        super().resizeEvent(event);self.update_size()

    def clear(self,message='选择一个视频开始剪辑'):
        self.image=QImage();self.message=message;self.update()

    def set_image(self,image):
        if image.isNull():return
        self.image=image;self.message=''
        if self.fixed_aspect is None:self.set_aspect(image.width(),image.height())
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.image.isNull():
            painter.setPen(Qt.gray);painter.drawText(self.rect(),Qt.AlignCenter,self.message);return
        if self.fixed_aspect is not None:
            from PyQt5.QtCore import QRect,QSize
            project_size=QSize(round(1000*self.fixed_aspect),1000).scaled(self.size(),Qt.KeepAspectRatio)
            project_rect=QRect((self.width()-project_size.width())//2,(self.height()-project_size.height())//2,project_size.width(),project_size.height())
            painter.fillRect(project_rect,Qt.black)
            size=self.image.size().scaled(project_size,Qt.KeepAspectRatio)
        else:size=self.image.size().scaled(self.size(),Qt.KeepAspectRatio)
        x=(self.width()-size.width())//2;y=(self.height()-size.height())//2
        from PyQt5.QtCore import QRect
        self.painted_rect=QRect(x,y,size.width(),size.height())
        painter.drawImage(self.painted_rect,self.image)


class CpuVideoSurface(QAbstractVideoSurface):
    image_ready=pyqtSignal(QImage)
    frame_received=pyqtSignal(QImage,object)
    def __init__(self,parent=None):
        super().__init__(parent);self.frame_count=0;self.last_image=QImage();self.epoch=0

    def start(self,format):
        self.epoch+=1
        return super().start(format)

    def supportedPixelFormats(self,handleType=QAbstractVideoBuffer.NoHandle):
        if handleType!=QAbstractVideoBuffer.NoHandle:return []
        return [QVideoFrame.Format_RGB32,QVideoFrame.Format_ARGB32,QVideoFrame.Format_RGB24]

    def present(self,frame):
        copy=QVideoFrame(frame)
        if not copy.isValid() or not copy.map(QAbstractVideoBuffer.ReadOnly):return False
        try:
            image_format=QVideoFrame.imageFormatFromPixelFormat(copy.pixelFormat())
            if image_format==QImage.Format_Invalid:return False
            bits=copy.bits();bits.setsize(copy.mappedBytes())
            image=QImage(bits,copy.width(),copy.height(),copy.bytesPerLine(),image_format).copy()
            from PyQt5.QtMultimedia import QVideoSurfaceFormat
            if self.surfaceFormat().scanLineDirection()==QVideoSurfaceFormat.BottomToTop:image=image.mirrored()
        finally:copy.unmap()
        self.frame_count+=1;self.last_image=image;self.image_ready.emit(image);self.frame_received.emit(image,(frame.startTime(),self.epoch))
        return True


class PreviewProxy:
    """Build a smaller playback file; editing/export always keep the source path."""
    def __init__(self,parent,ffmpeg,environment,progress_callback,ready_callback,error_callback):
        self.process=QProcess(parent);self.process.setProcessEnvironment(environment)
        self.ffmpeg=ffmpeg;self.progress_callback=progress_callback
        self.ready_callback=ready_callback;self.error_callback=error_callback
        self.process.readyReadStandardOutput.connect(self.read_progress)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.serial=0;self.active=None;self.queued=None
        self.buffer='';self.errors='';self.duration=1

    def prepare(self,info):
        self.serial+=1
        self.queued=None
        if self.process.state()!=QProcess.NotRunning:
            self.queued=info;self.process.kill();return
        self.start(info)

    def start(self,info):
        if info.width*info.height<=1280*720 and float(info.fps)<=30:return
        source=info.path;stat=source.stat()
        key=hashlib.sha256(f'{source}\0{stat.st_size}\0{stat.st_mtime_ns}\0v1'.encode()).hexdigest()
        cache=Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation))/'preview'
        try:cache.mkdir(parents=True,exist_ok=True)
        except OSError as error:self.error_callback(str(error));return
        output=cache/(key+'.mp4')
        if output.is_file() and output.stat().st_size>0:
            self.ready_callback(source,output);return
        temporary=cache/(key+'.'+uuid.uuid4().hex+'.part.mp4')
        self.active=(source,output,temporary,self.serial)
        self.buffer='';self.errors='';self.duration=max(info.duration,.001)
        self.progress_callback(0)
        fps=min(30,float(info.fps))
        arguments=['-hide_banner','-loglevel','warning','-n','-threads','2','-i',str(source),
            '-map','0:v:0','-map','0:a:0?',
            '-vf',f"scale=w='min(960,iw)':h='min(540,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2:flags=fast_bilinear,fps={fps:.9g}",
            '-c:v','libx264','-preset','ultrafast','-crf','26','-pix_fmt','yuv420p',
            '-c:a','aac','-b:a','128k','-threads','2','-filter_threads','2','-movflags','+faststart',
            '-progress','pipe:1','-stats_period','0.5',str(temporary)]
        self.process.start(self.ffmpeg,arguments)

    def read_progress(self):
        self.buffer+=bytes(self.process.readAllStandardOutput()).decode(errors='replace')
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if line.startswith('out_time_us=') and self.active and self.active[3]==self.serial:
                try:self.progress_callback(min(99,max(0,int(float(line.split('=',1)[1])/1e6/self.duration*100))))
                except ValueError:pass

    def read_errors(self):
        self.errors=(self.errors+bytes(self.process.readAllStandardError()).decode(errors='replace'))[-4000:]

    def process_error(self,error):
        if error==QProcess.FailedToStart:self.finished(1,QProcess.CrashExit)

    def finished(self,code,status):
        active=self.active;self.active=None
        self.read_errors()
        if active:
            source,output,temporary,serial=active
            if code==0 and status==QProcess.NormalExit and temporary.is_file() and temporary.stat().st_size>0:
                try:
                    temporary.replace(output)
                    if serial==self.serial:self.ready_callback(source,output)
                except OSError as error:
                    temporary.unlink(missing_ok=True)
                    if serial==self.serial:self.error_callback(str(error))
            else:
                temporary.unlink(missing_ok=True)
                if serial==self.serial:self.error_callback(self.errors or '预览缓存生成失败')
        if self.queued:
            queued=self.queued;self.queued=None;self.start(queued)

    def stop(self):
        self.serial+=1;self.queued=None
        if self.process.state()!=QProcess.NotRunning:self.process.kill()
