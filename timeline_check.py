"""Verify composite preview and editing through the actual timeline widget."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
from PyQt5.QtCore import QEvent,QMimeData,QPoint,QPointF,QTimer,Qt,QUrl
from PyQt5.QtGui import QContextMenuEvent,QDragEnterEvent,QDropEvent,QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication,QFileDialog,QSpinBox


class TimelineCheck:
    def __init__(self,window,folder,result):
        self.window=window;self.editor=window.editor;self.folder=Path(folder).resolve();self.result=Path(result).resolve()
        self.files=sorted(str(p) for p in self.folder.glob('*.mp4'))
        self.hashes=[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in self.files]
        self.checks={};self.seen_clips=set();self.playback_stalls=[];self.phase='starting';self.done=False;self.started=time.monotonic();self.ticking=False
        self.editor.test_mode=True;self.editor.player.setVolume(0);self.editor.export_finished.connect(self.exported)
        self.timer=QTimer(window);self.timer.setInterval(150);self.timer.timeout.connect(self.tick);self.timer.start()
        QTimer.singleShot(500,self.import_videos)
    def import_videos(self):
        try:
            if len(self.files)!=3:raise ValueError('Three fixtures required')
            ed=self.editor;old=QFileDialog.getOpenFileNames
            try:QFileDialog.getOpenFileNames=lambda *_a,**_k:(self.files,'视频');ed.choose_video()
            finally:QFileDialog.getOpenFileNames=old
            self.checks['warehouse_import']=ed.media_library.count()==3
            self.checks['directory_memory']=ed.import_directory()==str(self.folder)
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(p) for p in self.files])
            enter=QDragEnterEvent(QPoint(20,60),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(ed.timeline,enter)
            drop=QDropEvent(QPointF(20,60),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(ed.timeline,drop)
            self.checks['timeline_accepts_drop']=enter.isAccepted() and drop.isAccepted();self.phase='loading'
        except Exception as error:self.finish(str(error))
    def tick(self):
        if self.ticking or self.done:return
        self.ticking=True
        try:self.advance()
        except Exception as error:self.finish(str(error))
        finally:self.ticking=False
    def dominant(self):
        image=self.editor.video_canvas.image
        if image.isNull():return -1
        color=image.pixelColor(image.width()//2,image.height()//2)
        values=[color.red(),color.green(),color.blue()];return max(range(3),key=lambda i:values[i])
    def begin_wait(self,phase):self.phase=phase;self.stage_time=time.monotonic()
    def advance(self):
        ed=self.editor;p=ed.project;t=ed.timeline
        if time.monotonic()-self.started>60:self.finish('Timeline check timed out');return
        if self.phase=='loading' and len(p.clips)==3 and not ed.media_seek_pending:
            self.checks['one_project_duration']=p.frames==114 and abs(p.duration-3.8)<.001
            self.checks['manual_frame_controls_removed']=not ed.findChildren(QSpinBox)
            self.checks['all_clips_visible']=t.frames==114 and len(t.project.clips)==3
            self.original_colors={clip.uid:clip.color for clip in p.clips}
            ed.seek(0);ed.toggle_play();self.begin_wait('initial-play')
        elif self.phase=='initial-play':
            if ed.active_index is not None and ed.wanted_play:self.seen_clips.add(ed.active_index)
            if not ed.wanted_play and ed.current_frame<p.frames-1:self.playback_stalls.append(ed.current_frame)
            if (not ed.wanted_play and ed.current_frame==113) or time.monotonic()-self.stage_time>10:
                self.checks['autoplay_first_second_and_third']=self.seen_clips=={0,1,2} and not self.playback_stalls and ed.current_frame==113
                self.begin_wait('seek_green');ed.seek(p.offset(1)+5)
        elif self.phase=='seek_green' and time.monotonic()-self.stage_time>.7:
            self.checks['seek_second_video']=self.dominant()==1 and ed.current_frame==41
            ed.seek(p.offset(2)+5);self.begin_wait('seek_blue')
        elif self.phase=='seek_blue' and time.monotonic()-self.stage_time>.7:
            self.checks['seek_third_video']=self.dominant()==2 and ed.current_frame==71
            t.fit();self.first_uid=p.clips[0].uid
            start=QPoint(round(t.frame_x(18)),70);finish=QPoint(t.width()-15,70)
            QTest.mousePress(t,Qt.LeftButton,pos=start)
            event=QMouseEvent(QEvent.MouseMove,QPointF(finish),Qt.NoButton,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(t,event)
            QTest.mouseRelease(t,Qt.LeftButton,pos=finish)
            self.checks['drag_reorders_clips']=[str(c.info.path) for c in p.clips]==[self.files[1],self.files[2],self.files[0]]
            self.checks['colors_follow_clips']={clip.uid:clip.color for clip in p.clips}==self.original_colors
            image=t.grab().toImage()
            self.checks['rendered_colors_follow_clips']=all(image.pixelColor(round(t.frame_x(p.offset(i)+clip.frames/2)),95).name()==clip.color for i,clip in enumerate(p.clips))
            self.checks['format_stays_stable']=p.fps==30 and p.width==64 and p.height==64
            ed.seek(27);ed.toggle_play();self.begin_wait('playing')
        elif self.phase=='playing' and time.monotonic()-self.stage_time>1.1:
            self.checks['play_crosses_clip_boundary']=ed.active_index==1 and self.dominant()==2 and ed.current_frame>=30
            self.checks['global_playhead']=ed.current_frame>=30 and p.frames==114 and '114' in ed.position_label.text()
            ed.seek(0);self.begin_wait('selecting')
        elif self.phase=='selecting' and time.monotonic()-self.stage_time>.4:
            t.fit();t.clear_selection();QTest.mouseDClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(5)),70))
            self.checks['double_click_requires_selected_clip']=t.selection is None
            QTest.mouseClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(5)),70));QTest.qWait(QApplication.doubleClickInterval()+40)
            QTest.mouseDClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(5)),70))
            QTest.mouseDClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(15)),70))
            self.checks['double_click_selects_interval']=t.selection==(5,16)
            QTest.mouseDClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(50)),70))
            self.checks['interval_stays_in_selected_clip']=t.selection==(5,16)
            self.window.raise_();self.window.activateWindow();QApplication.setActiveWindow(self.window);t.setFocus()
            def choose_delete():
                menu=t.context_menu
                if menu.isVisible():
                    QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(menu.actions()[0]).center())
            QTimer.singleShot(70,choose_delete)
            event=QContextMenuEvent(QContextMenuEvent.Mouse,QPoint(100,70),t.mapToGlobal(QPoint(100,70)))
            QApplication.sendEvent(t,event)
            self.begin_wait('deleting')
        elif self.phase=='deleting' and time.monotonic()-self.stage_time>.4:
            self.checks['right_click_selected_clip_range_delete']=p.frames==103 and [(c.start,c.end) for c in p.clips]==[(0,5),(16,30),(0,48),(0,36)]
            self.window.raise_();self.window.activateWindow();QApplication.setActiveWindow(self.window);t.setFocus();self.begin_wait('undoing')
        elif self.phase=='undoing' and time.monotonic()-self.stage_time>.3:
            QApplication.setActiveWindow(self.window);t.setFocus()
            QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier)
            self.checks['ctrl_z_restores_delete']=p.frames==114 and [str(c.info.path) for c in p.clips]==[self.files[1],self.files[2],self.files[0]]
            self.target_uid=p.clips[0].uid
            pos=QPoint(round(t.frame_x(15)),70);QTest.mouseClick(t,Qt.LeftButton,pos=pos)
            self.checks['single_click_selects_clip']=t.selected_uid==self.target_uid
            QApplication.sendEvent(t,QContextMenuEvent(QContextMenuEvent.Mouse,pos,t.mapToGlobal(pos)))
            self.checks['clip_context_menu']=t.clip_delete_action.isVisible() and t.speed_menu.menuAction().isVisible() and not t.delete_action.isVisible()
            QTest.mouseClick(t.context_menu,Qt.LeftButton,pos=t.context_menu.actionGeometry(t.clip_delete_action).center())
            self.begin_wait('clip-deleted')
        elif self.phase=='clip-deleted' and time.monotonic()-self.stage_time>.3:
            self.checks['right_click_deletes_whole_clip']=p.frames==84 and len(p.clips)==2 and all(c.uid!=self.target_uid for c in p.clips)
            QApplication.setActiveWindow(self.window);t.setFocus();QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier)
            self.checks['undo_clip_deletion']=p.frames==114 and p.clips[0].uid==self.target_uid
            pos=QPoint(round(t.frame_x(15)),70);QTest.mouseClick(t,Qt.LeftButton,pos=pos)
            QApplication.sendEvent(t,QContextMenuEvent(QContextMenuEvent.Mouse,pos,t.mapToGlobal(pos)))
            next(action for value,action in t.speed_actions if value==2).trigger();t.context_menu.close()
            self.checks['independent_clip_speed']=p.frames==99 and [c.speed for c in p.clips]==[2,1,1] and p.clips[0].uid==self.target_uid
            ed.seek(0);ed.toggle_play();self.begin_wait('clip-speed-ready')
        elif self.phase=='clip-speed-ready' and not ed.media_seek_pending and ed.player.state()==ed.player.PlayingState:
            self.checks['clip_playback_rate']=ed.player.playbackRate()==2
            self.begin_wait('clip-speed-play')
        elif self.phase=='clip-speed-play' and time.monotonic()-self.stage_time>.9:
            self.checks['speed_switches_at_next_clip']=ed.active_index==1 and ed.player.playbackRate()==1 and ed.wanted_play and self.dominant()==2
            ed.seek(0);ed.output_directory.setText(str(self.result.parent));ed.output_name.setText('片段独立倍速检查')
            ed.output_name.textEdited.emit(ed.output_name.text());self.phase='speed-exporting';ed.start_export()
            if not ed.busy:raise ValueError('Clip speed export did not start')
        elif self.phase=='exporting-wait' and time.monotonic()-self.stage_time>.6:
            self.window.grab().save(str(self.result.with_suffix('.png')));self.phase='exporting';ed.start_export()
            if not ed.busy:raise ValueError('Project export did not start')
    def exported(self,passed,path):
        if self.phase not in ('exporting','speed-exporting'):return
        try:
            if not passed:raise ValueError('Export failed: '+self.editor.logs.toPlainText())
            env={k:v for k,v in os.environ.items() if k!='LD_LIBRARY_PATH'}
            metadata=json.loads(subprocess.check_output([shutil.which('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',path],env=env))
            video=next(s for s in metadata['streams'] if s['codec_type']=='video')
            if self.phase=='speed-exporting':
                self.checks['clip_speed_export_duration']=int(video['nb_frames'])==99 and abs(float(metadata['format']['duration'])-3.3)<.08
                self.checks['clip_speed_export_order']=True
                for seconds,channel in [(.25,1),(1,2),(2.8,0)]:
                    rgb=subprocess.check_output([shutil.which('ffmpeg'),'-v','error','-ss',str(seconds),'-i',path,'-frames:v','1','-vf','scale=1:1:flags=neighbor','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],env=env)
                    self.checks['clip_speed_export_order'] &= max(range(3),key=lambda i:rgb[i])==channel
                ed=self.editor;t=ed.timeline;ed.undo_project()
                self.checks['undo_clip_speed']=ed.project.frames==114 and all(c.speed==1 for c in ed.project.clips)
                t.fit();QTest.mouseClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(5)),70));QTest.qWait(QApplication.doubleClickInterval()+40)
                QTest.mouseDClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(5)),70))
                QTest.mouseDClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(15)),70));t.delete_action.trigger()
                ed.output_name.setText('时间线完整项目检查');ed.seek(0);self.begin_wait('exporting-wait');return
            self.checks['export_matches_timeline']=int(video['nb_frames'])==103 and abs(float(metadata['format']['duration'])-103/30)<.08
            self.checks['exported_order_and_deletion']=True
            for seconds,channel in [(.3,1),(1,2),(2.8,0)]:
                rgb=subprocess.check_output([shutil.which('ffmpeg'),'-v','error','-ss',str(seconds),'-i',path,'-frames:v','1','-vf','scale=1:1:flags=neighbor','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],env=env)
                self.checks['exported_order_and_deletion'] &= max(range(3),key=lambda i:rgb[i])==channel
            self.checks['source_videos_preserved']=[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in self.files]==self.hashes
            self.finish()
        except Exception as error:self.finish(str(error))
    def finish(self,error=''):
        if self.done:return
        self.done=True;self.timer.stop()
        payload={'passed':not error and all(self.checks.values()),'checks':self.checks,'error':error,'frame_count':self.editor.project.frames,
                 'rendered_frames':self.editor.surface.frame_count,'player_status':self.editor.player.mediaStatus()}
        self.result.write_text(json.dumps(payload,ensure_ascii=False,indent=2));print(json.dumps(payload,ensure_ascii=False),flush=True)
        self.editor.shutdown_preview();QApplication.instance().exit(0 if payload['passed'] else 1)
