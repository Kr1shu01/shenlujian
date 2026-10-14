"""Drag a desktop rectangle and return X11 capture coordinates."""
from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget


class AreaSelector(QWidget):
    selected=pyqtSignal(QRect)
    cancelled=pyqtSignal()

    def __init__(self,desktop_geometry,to_native=None):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(desktop_geometry)
        self.to_native=to_native or (lambda r:r)
        self.start_point=None;self.end_point=None;self.done=False

    def bounded_point(self,point):
        return QPoint(max(0,min(self.width(),point.x())),max(0,min(self.height(),point.y())))

    def selected_rectangle(self):
        if self.start_point is None or self.end_point is None:return QRect()
        a=self.start_point;b=self.end_point
        return QRect(min(a.x(),b.x()),min(a.y(),b.y()),abs(a.x()-b.x()),abs(a.y()-b.y()))

    def mousePressEvent(self,event):
        if event.button()==Qt.RightButton:self.close();return
        if event.button()==Qt.LeftButton:
            self.start_point=self.bounded_point(event.pos());self.end_point=self.start_point;self.update()

    def mouseMoveEvent(self,event):
        if self.start_point is not None:
            self.end_point=self.bounded_point(event.pos());self.update()

    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.LeftButton or self.start_point is None:return
        self.end_point=self.bounded_point(event.pos())
        rectangle=self.selected_rectangle()
        if rectangle.width()<2 or rectangle.height()<2:
            self.start_point=None;self.end_point=None;self.update();return
        rectangle.translate(self.geometry().topLeft())
        self.done=True;self.selected.emit(rectangle);self.close()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape:self.close()
        else:super().keyPressEvent(event)

    def closeEvent(self,event):
        self.releaseKeyboard()
        if not self.done:
            self.done=True;self.cancelled.emit()
        event.accept()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(),QColor(0,0,0,145))
        rectangle=self.selected_rectangle()
        text='拖动鼠标选择区域 · 松开完成 · Esc 取消'
        if rectangle.width()>0 and rectangle.height()>0:
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rectangle,Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor('#88e0c3'),2));painter.drawRect(rectangle.adjusted(1,1,-1,-1))
            global_rectangle=self.to_native(rectangle.translated(self.geometry().topLeft()))
            text=f'左 {global_rectangle.x()} · 上 {global_rectangle.y()} · 宽 {global_rectangle.width()} · 高 {global_rectangle.height()}   |   松开完成 · Esc 取消'
        font=painter.font();font.setPixelSize(20);painter.setFont(font)
        label_width=min(self.width()-32,painter.fontMetrics().horizontalAdvance(text)+36)
        box=QRect((self.width()-label_width)//2,24,label_width,48)
        painter.setPen(Qt.NoPen);painter.setBrush(QColor('#192331'));painter.drawRoundedRect(box,9,9)
        painter.setPen(QColor('#edf6f2'));painter.drawText(box,Qt.AlignCenter,text)
