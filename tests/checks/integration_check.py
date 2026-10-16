"""Desktop recording, editing and import regression check."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication


class IntegrationCheck:
    def __init__(self,window,source,result):
        self.window=window;self.source=Path(source).resolve();self.result=Path(result).resolve()
        self.phase='loading';self.results={};self.done=False
        self.original_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        editor=window.editor;editor.test_mode=True;editor.player.setVolume(0)
        editor.video_loaded.connect(self.loaded);editor.export_finished.connect(self.exported)
        window.recorder.process.finished.connect(self.recorded)
        QTimer.singleShot(400,lambda:editor.load_video(self.source))
        QTimer.singleShot(40000,lambda:self.finish(False,'Integration test timed out'))

    def loaded(self):
        editor=self.window.editor
        if self.phase=='recorded-import':
            self.results['recording_import']=(editor.info.path==self.window.recorder.last_saved)
            self.finish(all(self.results.values()));return
        if self.phase!='loading':return
        self.phase='preview';editor.toggle_play()
        QTimer.singleShot(1500,self.edit_and_export)

    def edit_and_export(self):
        editor=self.window.editor
        self.results['video_preview']=editor.player.position()>300 and not editor.player.error() and editor.surface.frame_count>10
        editor.seek(1)
        QTimer.singleShot(150,self.check_first_frame)

    def check_first_frame(self):
        editor=self.window.editor
        self.results['frame_step']=editor.current_frame==1
        editor.seek(2)
        QTimer.singleShot(150,self.begin_export)

    def begin_export(self):
        editor=self.window.editor
        self.results['frame_step']=self.results['frame_step'] and editor.current_frame==2
        editor.project.delete_range(150,editor.project.frames)
        editor.project.delete_range(30,60)
        editor.project.delete_range(60,61)
        editor.project_changed(60)
        editor.speed.setCurrentIndex(6)
        editor.output_directory.setText(str(self.result.parent));editor.output_name.setText('神录剪 中文倍速测试')
        self.phase='exporting';editor.start_export()
        if not editor.busy:self.finish(False,'Export did not start')

    def probe(self,path):
        return json.loads(subprocess.check_output([shutil.which('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(path)],
            env={k:v for k,v in __import__('os').environ.items() if k!='LD_LIBRARY_PATH'}))

    def exported(self,passed,path):
        if self.phase!='exporting':return
        if not passed:self.finish(False,'Export failed');return
        metadata=self.probe(path);video=next(s for s in metadata['streams'] if s['codec_type']=='video')
        self.results['editing_export']=video['codec_name']=='h264' and abs(float(metadata['format']['duration'])-(119/30/2))<.06
        self.results['audio_retained']=any(s['codec_type']=='audio' for s in metadata['streams'])
        self.results['original_preserved']=hashlib.sha256(self.source.read_bytes()).hexdigest()==self.original_hash
        self.phase='recording';recorder=self.window.recorder
        recorder.directory.setText(str(self.result.parent));recorder.name.setText('神录剪 录屏回归')
        recorder.timestamp.setChecked(False);recorder.minimize.setChecked(False)
        recorder.area.setCurrentIndex(recorder.area.count()-1);recorder.x.setValue(0);recorder.y.setValue(0)
        recorder.capture_w.setValue(960);recorder.capture_h.setValue(800)
        recorder.resolution.setCurrentIndex(recorder.resolution.count()-1)
        recorder.output_w.setValue(640);recorder.output_h.setValue(480);recorder.fps.setValue(24)
        recorder.start_recording();QTimer.singleShot(2700,recorder.stop_recording)

    def recorded(self,code,status):
        if self.phase!='recording':return
        if code or not self.window.recorder.last_saved:self.finish(False,'Recording regression failed');return
        metadata=self.probe(self.window.recorder.last_saved);stream=metadata['streams'][0]
        self.results['recording_regression']=(stream['width']==640 and stream['height']==480 and stream['avg_frame_rate']=='24/1')
        self.phase='recorded-import';self.window.import_recording()

    def finish(self,passed,reason=''):
        if self.done:return
        self.done=True
        payload={'passed':bool(passed),'checks':self.results,'reason':reason}
        self.result.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(json.dumps(payload,ensure_ascii=False),flush=True)
        self.window.editor.shutdown_preview()
        QApplication.instance().exit(0 if passed else 1)
