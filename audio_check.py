"""Actual UI verification of screen choices, library Delete and audio timeline."""
import json,math,os,struct,subprocess,time,hashlib
from pathlib import Path
from PyQt5.QtCore import QEvent,QMimeData,QPoint,QPointF,QRect,QTimer,Qt,QUrl
from PyQt5.QtGui import QDragEnterEvent,QDropEvent,QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication,QLabel
from capture_geometry import CaptureGeometry,ScreenMapping


class AudioCheck:
    def __init__(self,window,folder,result):
        self.window=window;self.ed=window.editor;self.folder=Path(folder);self.result=Path(result)
        self.video1=str(self.folder/'红色原声.mp4');self.video2=str(self.folder/'蓝色原声.mp4');self.song=str(self.folder/'音乐.wav')
        self.paths=[self.video1,self.video2,self.song];self.hashes=[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in self.paths]
        self.env={k:v for k,v in os.environ.items() if k!='LD_LIBRARY_PATH'}
        self.ed.test_mode=True;self.ed.player.setVolume(0);self.ed.export_finished.connect(self.exported)
        self.phase='starting';self.checks={};self.done=False;self.ticking=False;self.started=time.monotonic()
        self.timer=QTimer(window);self.timer.setInterval(150);self.timer.timeout.connect(self.tick);self.timer.start()
        QTimer.singleShot(500,self.begin)
    def begin(self):
        try:
            rec=self.window.recorder
            self.checks['default_fullscreen_has_no_pixel_size']=rec.area.currentText()=='全屏录制' and '2560' not in rec.capture_size_label.text()
            name=QApplication.primaryScreen().name()
            rec.capture_geometry=CaptureGeometry(QRect(0,0,6400,2160),[
                ScreenMapping('另一屏',QRect(0,0,2560,1440),QRect(0,0,2560,1440)),
                ScreenMapping(name,QRect(2560,0,3840,2160),QRect(2560,0,3840,2160))])
            rec.desktop_geometry=rec.capture_geometry.root;rec.populate_capture_regions()
            self.checks['dual_monitor_detected']=rec.area.count()==5 and rec.area.currentData()==(2560,0,3840,2160)
            rec.area.setCurrentIndex(1);options=rec.collect_options()
            self.checks['select_first_monitor_uses_its_bounds']=(options.x,options.y,options.width,options.height)==(0,0,2560,1440)
            rec.area.setCurrentIndex(2);options=rec.collect_options()
            self.checks['select_second_monitor_uses_its_bounds']=(options.x,options.y,options.width,options.height)==(2560,0,3840,2160)
            self.checks['monitor_names_do_not_show_resolution']=all('3840' not in rec.area.itemText(i) and '2560' not in rec.area.itemText(i) for i in range(rec.area.count()))
            rec.area.setCurrentIndex(0);rec.refresh_capture_geometry()
            self.checks['metadata_below_editor_heading_removed']=not self.ed.metadata.isVisible()
            labels=[label.text() for label in self.ed.findChildren(QLabel)]
            self.checks['renamed_asset_library']='素材库' in labels and '视频仓库' not in labels
            self.ed.import_files(self.paths);self.phase='importing'
        except Exception as error:self.finish(str(error))
    def tick(self):
        if self.done or self.ticking:return
        self.ticking=True
        try:self.advance()
        except Exception as error:self.finish(str(error))
        finally:self.ticking=False
    def wait(self,phase):self.phase=phase;self.stage=time.monotonic()
    def advance(self):
        ed=self.ed;p=ed.project;t=ed.timeline
        if time.monotonic()-self.started>70:raise ValueError('Audio UI check timed out at '+self.phase)
        if self.phase=='importing' and all(path in ed.media_library.infos for path in self.paths):
            self.checks['audio_imports_into_asset_library']=ed.media_library.count()==3 and not ed.media_library.infos[self.song].has_video
            ed.add_to_project([self.video1,self.video2]);self.phase='videos-loading'
        elif self.phase=='videos-loading' and len(p.clips)==2 and not ed.media_seek_pending:
            ed.seek(0);ed.next.click();self.checks['forward_button_jumps_5_seconds']=ed.current_frame==150 and ed.active_index==1 and '5' in ed.next.text()
            ed.previous.click();self.checks['back_button_jumps_5_seconds']=ed.current_frame==0 and '5' in ed.previous.text()
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(self.song)]);point=QPoint(round(t.frame_x(30)),140)
            enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(t,enter)
            drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(t,drop)
            self.checks['audio_drop_is_separate_track']=drop.isAccepted() and len(p.clips)==2 and len(p.audio_clips)==1 and p.audio_clips[0].offset==30
            self.wait('audio-ready')
        elif self.phase=='audio-ready' and time.monotonic()-self.stage>.7:
            self.uid=p.audio_clips[0].uid;t.fit()
            start=QPoint(round(t.frame_x(35)),140);end=QPoint(round(t.frame_x(185)),140)
            QTest.mousePress(t,Qt.LeftButton,pos=start)
            QApplication.sendEvent(t,QMouseEvent(QEvent.MouseMove,QPointF(end),Qt.NoButton,Qt.LeftButton,Qt.NoModifier));QTest.mouseRelease(t,Qt.LeftButton,pos=end)
            self.checks['drag_moves_audio_start']=p.audio_clips[0].offset==180 and p.frames==270
            self.window.raise_();self.window.activateWindow();QApplication.setActiveWindow(self.window)
            library=ed.media_library;library.clearSelection();item=library.items[self.video2];item.setSelected(True);library.setFocus()
            QTest.keyClick(library,Qt.Key_Delete)
            self.checks['Delete_removes_asset_not_timeline_or_file']=library.count()==2 and self.video2 not in library.items and len(p.clips)==2 and len(p.audio_clips)==1 and Path(self.video2).is_file()
            t.setFocus();QTest.mouseClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(195)),140));QTest.keyClick(t,Qt.Key_Delete)
            self.checks['Delete_removes_only_audio_clip']=not p.audio_clips and len(p.clips)==2
            QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier);self.checks['undo_restores_audio_clip']=len(p.audio_clips)==1 and p.audio_clips[0].offset==180
            ed.seek(180);ed.toggle_play();self.wait('playing')
        elif self.phase=='playing' and time.monotonic()-self.stage>.9:
            entry=ed.audio_preview.players.get(self.uid)
            self.checks['audio_preview_is_playing_and_synchronized']=bool(entry) and entry['player'].state()==entry['player'].PlayingState and entry['player'].position()>400 and abs(entry['player'].position()-(ed.current_frame-180)/30*1000)<250
            self.checks['video_preview_continues_with_audio']=ed.active_index==1 and ed.wanted_play and ed.surface.frame_count>5
            self.wait('tail')
        elif self.phase=='tail' and ed.current_frame>=250 and ed.wanted_play:
            entry=ed.audio_preview.players[self.uid]
            self.checks['audio_tail_continues_after_video']=ed._tail_mode and entry['player'].state()==entry['player'].PlayingState
            self.window.grab().save(str(self.result.with_suffix('.png')))
            ed.seek(0);ed.output_directory.setText(str(self.result.parent));ed.output_name.setText('独立音轨界面验收');ed.output_name.textEdited.emit(ed.output_name.text())
            self.phase='exporting';ed.start_export()
            if not ed.busy:raise ValueError('Export did not start')
        elif self.phase=='audio-only-loading' and p.audio_clips and not p.clips:
            ed.seek(0);ed.toggle_play();self.wait('audio-only-playing')
        elif self.phase=='audio-only-playing' and time.monotonic()-self.stage>1:
            entry=ed.audio_preview.players.get(p.audio_clips[0].uid)
            self.checks['audio_only_project_previews']=ed.current_frame>=20 and ed.wanted_play and entry and entry['player'].position()>400
            self.checks['source_files_preserved']=[hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in self.paths]==self.hashes
            self.finish()
    def amplitude(self,path,seconds,hz):
        raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(seconds),'-i',path,'-t','0.1','-vn','-ac','1','-ar','48000','-f','f32le','pipe:1'],env=self.env)
        values=struct.unpack('<'+'f'*(len(raw)//4),raw);n=len(values)
        return 2/n*math.hypot(sum(v*math.cos(2*math.pi*hz*i/48000) for i,v in enumerate(values)),sum(v*math.sin(2*math.pi*hz*i/48000) for i,v in enumerate(values)))
    def exported(self,passed,path):
        if self.phase!='exporting':return
        try:
            if not passed:raise ValueError(self.ed.logs.toPlainText())
            data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',path],env=self.env))
            video=next(s for s in data['streams'] if s['codec_type']=='video')
            self.checks['export_contains_video_and_audio']=any(s['codec_type']=='audio' for s in data['streams']) and int(video['nb_frames'])==270 and abs(float(data['format']['duration'])-9)<.08
            self.checks['export_keeps_original_voice_before_music']=self.amplitude(path,.5,440)>.04 and self.amplitude(path,.5,880)<.015
            self.checks['export_mixes_music_at_dragged_start']=self.amplitude(path,6.5,660)>.04 and self.amplitude(path,6.5,880)>.04
            self.checks['export_includes_audio_tail']=self.amplitude(path,8.5,880)>.04 and self.amplitude(path,8.5,660)<.015
            self.ed.clear_project();self.ed.add_to_project([self.song]);self.phase='audio-only-loading'
        except Exception as error:self.finish(str(error))
    def finish(self,error=''):
        if self.done:return
        self.done=True;self.timer.stop();self.ed.shutdown_preview();self.window.hotkeys.close()
        result={'passed':not error and all(self.checks.values()),'checks':self.checks,'error':error}
        self.result.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
        QApplication.instance().exit(0 if result['passed'] else 1)
