"""Editable clip strip, range selection, and project playhead."""
from PyQt5.QtCore import QPoint,QRect,QTimer,Qt,pyqtSignal
from PyQt5.QtGui import QColor,QPainter,QPen,QPolygon
from PyQt5.QtWidgets import QAction,QApplication,QInputDialog,QMenu,QWidget


class ProjectTimeline(QWidget):
    seek_requested=pyqtSignal(int)
    move_requested=pyqtSignal(str,int)
    files_dropped=pyqtSignal(object,int)
    audio_files_dropped=pyqtSignal(object,int)
    selection_changed=pyqtSignal(object)
    delete_requested=pyqtSignal()
    undo_requested=pyqtSignal()
    clip_selected=pyqtSignal(object)
    clip_delete_requested=pyqtSignal(str)
    clip_speed_requested=pyqtSignal(str,float)

    def __init__(self,project,parent=None):
        super().__init__(parent);self.project=project;self.cursor=0;self.selection=None;self.anchor=None;self.selection_uid=None;self.range_ready_uid=None
        self.zoom=1.;self.view_start=0.;self.press=None;self.drag_uid=None;self.drag_target=None;self.dragging=False
        self.double_click=False;self.undo_enabled=False;self.thumbnail_lookup=None;self.selected_uid=None;self.drag_audio=False;self.drag_anchor=0;self.drop_frame=None
        self.click_timer=QTimer(self);self.click_timer.setSingleShot(True);self.click_timer.timeout.connect(self.finish_single_click)
        self.setMinimumHeight(212);self.setAcceptDrops(True);self.setFocusPolicy(Qt.StrongFocus);self.setMouseTracking(True)
        self.setToolTip('单击选中片段，右键删除或设置片段倍速；拖动调整顺序；先单击选中片段，再在该片段内双击两个位置选中区间，右键只删除该片段的选区；Ctrl+Z 撤销。Ctrl+滚轮缩放，滚轮平移。')
        self.delete_action=QAction('删除选中区间',self);self.delete_action.triggered.connect(self.delete_requested)
        self.undo_action=QAction('撤销  Ctrl+Z',self);self.undo_action.triggered.connect(self.undo_requested)
        self.clip_delete_action=QAction('删除选中片段',self)
        self.clip_delete_action.triggered.connect(lambda:self.clip_delete_requested.emit(self.selected_uid) if self.selected_uid else None)
        self.context_menu=QMenu(self);self.context_menu.addAction(self.delete_action);self.context_menu.addAction(self.clip_delete_action)
        self.speed_menu=self.context_menu.addMenu('片段倍速');self.speed_actions=[]
        for speed in (.25,.5,.75,1,1.25,1.5,2,3,4):
            action=self.speed_menu.addAction(f'{speed:g} ×');action.setCheckable(True)
            action.triggered.connect(lambda _checked=False,value=speed:self.change_selected_speed(value));self.speed_actions.append((speed,action))
        self.speed_menu.addSeparator();self.speed_menu.addAction('自定义…',self.custom_clip_speed)
        self.context_menu.addSeparator();self.context_menu.addAction(self.undo_action)

    @property
    def frames(self):return self.project.frames
    @property
    def scale(self):return max(.001,(self.width()-24)/max(1,self.frames)*self.zoom)
    def frame_x(self,frame):return 12+(frame-self.view_start)*self.scale
    def frame_at(self,x):return max(0,min(max(0,self.frames-1),round((x-12)/self.scale+self.view_start)))
    def clamp_view(self):self.view_start=max(0,min(max(0,self.frames-(self.width()-24)/self.scale),self.view_start))
    def fit(self):self.zoom=1.;self.view_start=0.;self.update()
    def set_zoom(self,factor,center=None):
        center=self.width()/2 if center is None else center
        frame=(center-12)/self.scale+self.view_start
        self.zoom=max(1,min(128,factor));self.view_start=frame-(center-12)/self.scale;self.clamp_view();self.update()
    def refresh(self):
        self.cursor=min(self.cursor,max(0,self.frames-1));self.clamp_view();self.undo_enabled=bool(self.project.history);self.update()
    def clear_selection(self):
        self.click_timer.stop();self.selection=None;self.anchor=None;self.selection_uid=None;self.range_ready_uid=None;self.selected_uid=None
        self.selection_changed.emit(None);self.clip_selected.emit(None);self.update()
    def select_clip(self,uid,clear_range=True):
        changed=uid!=self.selected_uid;self.selected_uid=uid
        if changed:self.range_ready_uid=None
        if clear_range or changed:
            self.selection=None;self.anchor=None;self.selection_uid=None;self.selection_changed.emit(None)
        if clear_range:self.range_ready_uid=uid
        self.clip_selected.emit(uid);self.update()
    def finish_single_click(self):
        self.selection=None;self.anchor=None;self.selection_uid=None;self.range_ready_uid=self.selected_uid
        self.selection_changed.emit(None);self.clip_selected.emit(self.selected_uid);self.update()
    def selected_clip(self):return self.project.get_clip(self.selected_uid)
    def change_selected_speed(self,value):
        if self.selected_uid:self.clip_speed_requested.emit(self.selected_uid,value)
    def custom_clip_speed(self):
        clip=self.selected_clip()
        if clip:
            value,accepted=QInputDialog.getDouble(self,'片段倍速',clip.info.path.name+' · 倍速',clip.speed,.1,16,2)
            if accepted:self.change_selected_speed(value)
    def select_frame(self,frame):
        clip=self.selected_clip()
        if not clip or self.range_ready_uid!=clip.uid:return
        offset=clip.offset if clip in self.project.audio_clips else self.project.offset(next(i for i,c in enumerate(self.project.clips) if c.uid==clip.uid))
        if not offset<=frame<offset+clip.frames:return
        self.click_timer.stop();self.selection_uid=clip.uid
        if self.anchor is None:self.anchor=frame;self.selection=(frame,frame+1)
        else:self.selection=(min(self.anchor,frame),max(self.anchor,frame)+1);self.anchor=None
        self.selection_changed.emit(self.selection);self.seek_requested.emit(frame);self.update()
    def insertion_at(self,x):
        offset=0
        for index,clip in enumerate(self.project.clips):
            if x<self.frame_x(offset+clip.frames/2):return index
            offset+=clip.frames
        return len(self.project.clips)
    def clip_at(self,x):
        if not self.frames:return None
        frame=self.frame_at(x)
        if frame>=self.project.video_frames:return None
        result=self.project.locate(frame);return result[1] if result else None
    def audio_at(self,x):
        frame=self.frame_at(x)
        return next((c for c in reversed(self.project.audio_clips) if c.offset<=frame<c.offset+c.frames),None)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.setPen(QColor('#93a5ba'))
        if not self.frames:
            p.drawText(self.rect(),Qt.AlignCenter,'把素材拖到这里，建立视频轨道和音轨');return
        fps=float(self.project.fps)
        for i in range(7):
            x=12+(self.width()-24)*i/6;frame=(x-12)/self.scale+self.view_start
            seconds=frame/fps
            p.drawText(QRect(int(x)-32,0,72,22),Qt.AlignCenter,f'{int(seconds)//60:02d}:{seconds%60:05.2f}')
            p.drawLine(int(x),26,int(x),32)
        offset=0
        for i,clip in enumerate(self.project.clips):
            a=self.frame_x(offset);b=self.frame_x(offset+clip.frames);offset+=clip.frames
            if b<0 or a>self.width():continue
            rect=QRect(round(a)+1,42,max(1,round(b-a)-2),57)
            p.setBrush(QColor(clip.color));p.setPen(QPen(QColor('#77e2bc') if clip.uid in (self.drag_uid,self.selected_uid) else QColor('#6b8097'),3 if clip.uid==self.selected_uid else 1))
            p.drawRoundedRect(rect,6,6)
            if rect.width()>30:
                padding=6
                if self.thumbnail_lookup and rect.width()>160:
                    item=self.thumbnail_lookup(str(clip.info.path))
                    if item:
                        from PyQt5.QtCore import QSize
                        p.drawPixmap(rect.x()+6,rect.y()+8,item.icon().pixmap(QSize(64,40)));padding=76
                p.setPen(QColor('#f0f4f8'))
                text=p.fontMetrics().elidedText(f'{i+1}. {clip.info.path.name}',Qt.ElideRight,max(1,rect.width()-padding-6))
                p.drawText(rect.adjusted(padding,4,-6,-22),Qt.AlignLeft|Qt.AlignVCenter,text)
                p.setPen(QColor('#c1d0dc'));p.drawText(rect.adjusted(padding,27,-6,-3),Qt.AlignLeft|Qt.AlignVCenter,f'{clip.frames/fps:.2f} 秒 · {clip.speed:g} ×')
        p.setPen(QColor('#93a5ba'));p.drawText(QRect(12,22,100,18),Qt.AlignLeft,'视频')
        p.drawLine(12,114,self.width()-12,114);p.drawText(QRect(12,172,100,20),Qt.AlignLeft,'音轨')
        if not self.project.audio_clips:p.drawText(QRect(12,120,self.width()-24,46),Qt.AlignCenter,'将音频素材拖到这里')
        for clip in self.project.audio_clips:
            a=self.frame_x(clip.offset);b=self.frame_x(clip.offset+clip.frames)
            if b<0 or a>self.width():continue
            rect=QRect(round(a)+1,122,max(1,round(b-a)-2),44)
            p.setBrush(QColor(clip.color));p.setPen(QPen(QColor('#77e2bc') if clip.uid==self.selected_uid else QColor('#6b8097'),3 if clip.uid==self.selected_uid else 1));p.drawRoundedRect(rect,6,6)
            padding=6
            if self.thumbnail_lookup and rect.width()>160:
                item=self.thumbnail_lookup(str(clip.info.path))
                if item:p.drawPixmap(rect.x()+6,rect.y()+7,item.icon().pixmap(64,30));padding=76
            p.setPen(QColor('#f0f4f8'))
            text=p.fontMetrics().elidedText('♪ '+clip.info.path.name,Qt.ElideRight,max(1,rect.width()-padding-6))
            p.drawText(rect.adjusted(padding,2,-6,-18),Qt.AlignLeft|Qt.AlignVCenter,text)
            p.setPen(QColor('#c1d0dc'));p.drawText(rect.adjusted(padding,22,-6,-2),Qt.AlignLeft|Qt.AlignVCenter,f'{clip.frames/fps:.2f} 秒 · {clip.speed:g} ×')
        if self.selection:
            a,b=self.selection;x=self.frame_x(a);w=self.frame_x(b)-x
            p.setPen(QPen(QColor('#f3d88c'),2));p.setBrush(QColor(243,216,140,60))
            audio_selection=any(c.uid==self.selection_uid for c in self.project.audio_clips)
            p.drawRect(QRect(round(x),122 if audio_selection else 42,max(2,round(w)),44 if audio_selection else 57))
            p.setPen(QColor('#f3d88c'));p.drawText(QRect(round(x),182,max(110,round(w)),24),Qt.AlignLeft,f'选区 {b-a} 帧')
        x=round(self.frame_x(self.cursor));p.setPen(QPen(QColor('#eaf0f8'),2));p.drawLine(x,24,x,172)
        p.setBrush(QColor('#eaf0f8'));p.drawPolygon(QPolygon([QPoint(x-5,24),QPoint(x+5,24),QPoint(x,31)]))
        if self.drag_target is not None:
            x=round(self.frame_x(self.drag_target if self.drag_audio else self.project.offset(self.drag_target)))
            p.setPen(QPen(QColor('#77e2bc'),4));p.drawLine(x,116 if self.drag_audio else 34,x,169 if self.drag_audio else 103)

    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton:return
        self.click_timer.stop();self.setFocus();self.double_click=False;self.press=event.pos();self.dragging=False
        self.drag_audio=118<=event.y()<=170
        clip=self.audio_at(event.x()) if self.drag_audio else self.clip_at(event.x()) if 42<=event.y()<=99 else None
        self.drag_anchor=self.frame_at(event.x())-clip.offset if clip and self.drag_audio else 0
        self.drag_uid=clip.uid if clip else None
        self.select_clip(self.drag_uid,clear_range=False)
        if self.frames:self.seek_requested.emit(self.frame_at(event.x()))
    def mouseMoveEvent(self,event):
        if not event.buttons()&Qt.LeftButton or self.press is None:return
        if self.drag_uid:
            if (event.pos()-self.press).manhattanLength()>=QApplication.startDragDistance():self.dragging=True
            if self.dragging:
                self.drag_target=max(0,round((event.x()-12)/self.scale+self.view_start-self.drag_anchor)) if self.drag_audio else self.insertion_at(event.x());self.update()
        elif self.frames:self.seek_requested.emit(self.frame_at(event.x()))
    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.LeftButton:return
        if self.dragging and self.drag_uid and self.drag_target is not None:self.move_requested.emit(self.drag_uid,self.drag_target)
        if not self.dragging and not self.double_click:self.click_timer.start(QApplication.doubleClickInterval()+20)
        self.press=None;self.drag_uid=None;self.drag_target=None;self.dragging=False;self.update()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.click_timer.stop();self.double_click=True;self.press=None;self.drag_uid=None;self.dragging=False
            clip=self.audio_at(event.x()) if 118<=event.y()<=170 else self.clip_at(event.x()) if 42<=event.y()<=99 else None
            if clip and clip.uid==self.selected_uid:self.select_frame(self.frame_at(event.x()))
    def contextMenuEvent(self,event):
        self.click_timer.stop()
        if self.selected_uid and not self.selection:self.select_clip(self.selected_uid)
        elif not self.selection and (42<=event.y()<=99 or 118<=event.y()<=170):
            clip=self.audio_at(event.x()) if event.y()>=118 else self.clip_at(event.x())
            if clip:self.select_clip(clip.uid)
        clip=self.selected_clip()
        self.delete_action.setVisible(bool(self.selection));self.delete_action.setEnabled(bool(self.selection))
        self.clip_delete_action.setVisible(bool(clip));self.speed_menu.menuAction().setVisible(bool(clip))
        self.undo_action.setEnabled(self.undo_enabled)
        if clip:
            for value,action in self.speed_actions:action.setChecked(abs(clip.speed-value)<1e-6)
        self.context_menu.popup(event.globalPos());event.accept()
    def wheelEvent(self,event):
        delta=event.angleDelta().y()
        if event.modifiers()&Qt.ControlModifier:self.set_zoom(self.zoom*(1.25 if delta>0 else .8),event.pos().x())
        else:self.view_start-=delta/120*(self.width()-24)/self.scale/8;self.clamp_view();self.update()
        event.accept()
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls():
            self.drag_target=self.insertion_at(event.pos().x());self.update();event.acceptProposedAction()
    def dragLeaveEvent(self,event):self.drag_target=None;self.update()
    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.drop_frame=max(0,round((event.pos().x()-12)/self.scale+self.view_start))
            if event.pos().y()>=116:self.audio_files_dropped.emit(paths,self.drop_frame)
            else:self.files_dropped.emit(paths,self.insertion_at(event.pos().x()))
            self.drop_frame=None;event.setDropAction(Qt.CopyAction);event.accept()
        self.drag_target=None;self.update()
