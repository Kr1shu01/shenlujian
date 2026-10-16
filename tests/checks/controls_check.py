"""Exercise native global keys, recording sizes, edit keys and actual exports."""
import ctypes as C,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
from PyQt5.QtCore import QPoint,QRect,Qt,QTimer
from PyQt5.QtGui import QColor,QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication,QWidget


class CaptureMarker(QWidget):
    def __init__(self):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating);self.setWindowFlag(Qt.WindowDoesNotAcceptFocus,True)
        self.setGeometry(100,120,320,180)
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('red'));p.fillRect(QRect(0,0,40,40),QColor('green'));p.fillRect(QRect(280,140,40,40),QColor('blue'))


class ControlsCheck:
    def __init__(self,window,folder,result):
        self.window=window;self.ed=window.editor;self.rec=window.recorder;self.folder=Path(folder);self.result=Path(result)
        self.phase='starting';self.checks={};self.record_index=0;self.quality_index=0;self.done=False;self.ticking=False;self.started=time.monotonic()
        self.env={k:v for k,v in os.environ.items() if k!='LD_LIBRARY_PATH'}
        self.ed.test_mode=True;self.ed.player.setVolume(0);self.ed.export_finished.connect(self.exported)
        self.rec.process.finished.connect(self.recorded)
        self.marker=CaptureMarker();self.records=[]
        self.timer=QTimer(window);self.timer.setInterval(150);self.timer.timeout.connect(self.tick);self.timer.start()
        self.x=C.CDLL('libX11.so.6');self.xt=C.CDLL('libXtst.so.6')
        self.x.XOpenDisplay.restype=C.c_void_p;self.x.XOpenDisplay.argtypes=[C.c_char_p];self.display=self.x.XOpenDisplay(None)
        self.x.XStringToKeysym.argtypes=[C.c_char_p];self.x.XStringToKeysym.restype=C.c_ulong
        self.x.XKeysymToKeycode.argtypes=[C.c_void_p,C.c_ulong];self.x.XKeysymToKeycode.restype=C.c_uint
        self.x.XFlush.argtypes=[C.c_void_p];self.x.XCloseDisplay.argtypes=[C.c_void_p]
        self.xt.XTestFakeKeyEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
        QTimer.singleShot(500,self.setup)
    def key(self,name):
        code=self.x.XKeysymToKeycode(self.display,self.x.XStringToKeysym(name.encode()))
        self.xt.XTestFakeKeyEvent(self.display,code,1,0);self.xt.XTestFakeKeyEvent(self.display,code,0,0);self.x.XFlush(self.display)
    def probe(self,path):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],env=self.env))
    def setup(self):
        try:
            self.checks['global_F9_F10_registered']=self.window.hotkeys.registered=={'F9','F10'}
            if not self.checks['global_F9_F10_registered']:raise ValueError(self.window.hotkeys.error or 'Global keys unavailable')
            rec=self.rec
            self.checks['native_desktop_bounds']=rec.desktop_geometry==QRect(0,0,2560,1440)
            rec.settings.setValue('resolution',5);rec.settings.remove('resolution_size');rec.load_settings()
            self.checks['legacy_custom_size_setting']=rec.resolution.currentData() is None
            rec.directory.setText(str(self.result.parent));rec.timestamp.setChecked(False);rec.minimize.setChecked(True);rec.fps.setValue(5)
            for dimensions in [(1920,1080),(2560,1440),(3840,2160)]:
                self.checks[f'preset_{dimensions[0]}']=any(rec.resolution.itemData(i)==dimensions for i in range(rec.resolution.count()))
            self.start_recording_case()
        except Exception as error:self.finish(str(error))
    def start_recording_case(self):
        rec=self.rec
        if self.record_index<3:
            rec.area.setCurrentIndex(0);size=[(1920,1080),(2560,1440),(3840,2160)][self.record_index]
            rec.resolution.setCurrentIndex(next(i for i in range(rec.resolution.count()) if rec.resolution.itemData(i)==size))
            self.expected_size=size;self.expected_capture=(0,0,2560,1440)
            self.trigger_start()
        else:
            self.phase='selecting';rec.select_area()
    def trigger_start(self):
        rec=self.rec;rec.name.setText(f'录制快捷键_{self.record_index}')
        options=rec.collect_options();args=recorder_args(options,self.result.parent/'placeholder.mp4')
        self.checks[f'capture_coordinates_{self.record_index}']=args[args.index('-i')+1]==f'{options.display}+{self.expected_capture[0]},{self.expected_capture[1]}' and (options.x,options.y,options.width,options.height)==self.expected_capture
        self.checks[f'recording_size_label_{self.record_index}']=f'{self.expected_size[0]} × {self.expected_size[1]}' in rec.capture_size_label.text()
        self.window.showMinimized();self.phase='record-start';self.stage=time.monotonic();self.key('F9')
    def tick(self):
        if self.done or self.ticking:return
        self.ticking=True
        try:self.advance()
        except Exception as error:self.finish(str(error))
        finally:self.ticking=False
    def advance(self):
        if time.monotonic()-self.started>90:raise ValueError('Controls check timed out at '+self.phase+'; state='+self.rec.state+'; keyboard grab='+str(QWidget.keyboardGrabber())+'; '+self.rec.logs.toPlainText()[-1500:])
        rec=self.rec;ed=self.ed
        if self.phase=='record-start' and rec.state=='recording':
            self.checks[f'F9_starts_minimized_{self.record_index}']=self.window.isMinimized();self.phase='recording';self.stage=time.monotonic()
        elif self.phase=='recording' and time.monotonic()-self.stage>1.7:
            self.phase='record-stop';self.key('F10')
        elif self.phase=='selecting' and getattr(rec,'area_selector',None):
            selector=rec.area_selector
            QTest.mousePress(selector,Qt.LeftButton,pos=QPoint(100,120));QTest.mouseRelease(selector,Qt.LeftButton,pos=QPoint(420,300))
            self.checks['mouse_selected_native_coordinates']=(rec.x.value(),rec.y.value(),rec.capture_w.value(),rec.capture_h.value())==(100,120,320,180)
            self.expected_capture=(100,120,320,180);self.expected_size=(1000,776)
            rec.resolution.setCurrentIndex(rec.resolution.count()-1);rec.output_w.setValue(1001);rec.output_h.setValue(777)
            self.marker.show();self.marker.raise_();self.phase='marker-wait';self.stage=time.monotonic()
        elif self.phase=='marker-wait' and time.monotonic()-self.stage>.4:self.trigger_start()
        elif self.phase=='loading-editor' and len(ed.project.clips)==2 and not ed.media_seek_pending:
            self.keyboard_checks();ed.clear_project();ed.load_video(self.folder/'export_2k.mp4');self.phase='loading-export'
        elif self.phase=='loading-export' and len(ed.project.clips)==1 and ed.project.width==2560:
            expected=['高清 · 2560 × 1440','标准 · 1920 × 1080','省空间 · 1280 × 720']
            self.checks['quality_options_show_real_sizes']=[ed.export_quality.itemText(i) for i in range(3)]==expected
            self.export_next()
    def recorded(self,code,status):
        if self.phase!='record-stop':return
        try:
            if code or not self.rec.last_saved:raise ValueError('Recording failed: '+self.rec.logs.toPlainText())
            path=self.rec.last_saved;video=next(s for s in self.probe(path)['streams'] if s['codec_type']=='video')
            self.checks[f'F10_saves_actual_resolution_{self.record_index}']=(video['width'],video['height'])==self.expected_size and video['codec_name']=='h264'
            self.records.append(str(path))
            if self.record_index==3:
                self.checks['selected_area_contains_correct_pixels']=True
                for x,y,channel in [(.05,.2,1),(.5,.5,0),(.95,.8,2)]:
                    rgb=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-frames:v','1','-vf',f'crop=2:2:{int(x*1000)//2*2}:{int(y*776)//2*2},scale=1:1:flags=neighbor','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],env=self.env)
                    self.checks['selected_area_contains_correct_pixels'] &= max(range(3),key=lambda i:rgb[i])==channel
                self.marker.hide();self.record_index=4;rec=self.rec;rec.area.setCurrentIndex(0)
                rec.resolution.setCurrentIndex(rec.resolution.count()-1);rec.output_w.setValue(640);rec.output_h.setValue(480);rec.fps.setValue(30)
                self.expected_capture=(0,0,2560,1440);self.expected_size=(640,480)
                self.trigger_start();self.key('F10');self.phase='record-stop'
            elif self.record_index==4:
                self.checks['immediate_F9_F10_saves_nonempty_video']=int(video.get('nb_frames',0))>=1
                ed=self.ed;ed.add_to_project([str(self.folder/'edit_12s.mp4')]*2);self.phase='loading-editor'
            else:self.record_index+=1;self.start_recording_case()
        except Exception as error:self.finish(str(error))
    def keyboard_checks(self):
        ed=self.ed;t=ed.timeline;self.window.showMaximized();QApplication.setActiveWindow(self.window);t.setFocus()
        ed.seek(350);QTest.keyClick(t,Qt.Key_Right)
        self.checks['right_skips_5_seconds_across_clips']=ed.current_frame==500 and ed.active_index==1
        QTest.keyClick(t,Qt.Key_Left);self.checks['left_skips_5_seconds_across_clips']=ed.current_frame==350 and ed.active_index==0
        ed.seek(0);QTest.keyClick(t,Qt.Key_Left);self.checks['left_clamps_start']=ed.current_frame==0
        ed.seek(ed.project.frames-1);QTest.keyClick(t,Qt.Key_Right);self.checks['right_clamps_end']=ed.current_frame==719
        ed.seek(0);t.fit();uid=ed.project.clips[0].uid
        QTest.mouseClick(t,Qt.LeftButton,pos=QPoint(round(t.frame_x(60)),70));QTest.keyClick(t,Qt.Key_Delete)
        self.checks['Delete_removes_only_single_selected_clip']=len(ed.project.clips)==1 and ed.project.frames==360 and all(c.uid!=uid for c in ed.project.clips)
        QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier);self.checks['Ctrl_Z_undoes_Delete']=ed.project.frames==720
        t.clear_selection();QTest.keyClick(t,Qt.Key_Delete);self.checks['Delete_without_single_selection_is_safe']=ed.project.frames==720
        ed.output_name.setText('abc');ed.output_name.setFocus();ed.output_name.setCursorPosition(0);frame=ed.current_frame
        QTest.keyClick(ed.output_name,Qt.Key_Delete);QTest.keyClick(ed.output_name,Qt.Key_Right)
        self.checks['edit_fields_keep_normal_Delete_and_arrows']=ed.output_name.text()=='bc' and ed.output_name.cursorPosition()==1 and ed.current_frame==frame
    def export_next(self):
        ed=self.ed;ed.export_quality.setCurrentIndex(self.quality_index);self.expected_size=[(2560,1440),(1920,1080),(1280,720)][self.quality_index]
        self.checks[f'export_summary_{self.quality_index}']=f'{self.expected_size[0]} × {self.expected_size[1]}' in ed.plan_label.text()
        ed.output_directory.setText(str(self.result.parent));ed.output_name.setText(f'实际导出分辨率_{self.quality_index}');self.phase='exporting';ed.start_export()
        if not ed.busy:raise ValueError('Export not started')
    def exported(self,passed,path):
        if self.phase!='exporting':return
        try:
            if not passed:raise ValueError('Export failed: '+self.ed.logs.toPlainText())
            video=next(s for s in self.probe(path)['streams'] if s['codec_type']=='video')
            self.checks[f'quality_matches_ffprobe_{self.quality_index}']=(video['width'],video['height'])==self.expected_size
            self.quality_index+=1
            if self.quality_index<3:self.export_next()
            else:self.finish()
        except Exception as error:self.finish(str(error))
    def finish(self,error=''):
        if self.done:return
        self.done=True;self.timer.stop();self.marker.close();self.ed.shutdown_preview();self.window.hotkeys.close()
        if self.display:self.x.XCloseDisplay(self.display);self.display=None
        result={'passed':not error and all(self.checks.values()),'checks':self.checks,'error':error,'recordings':self.records}
        self.result.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
        QApplication.instance().exit(0 if result['passed'] else 1)


def recorder_args(options,path):
    from app.recording.commands import ffmpeg_arguments
    return ffmpeg_arguments(options,path)
