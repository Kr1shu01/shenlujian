"""Desktop regression check: verify rendered frames, not just the player clock."""
import hashlib
import json
import time
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication


class PreviewCheck:
    def __init__(self,window,source,result):
        self.window=window;self.editor=window.editor;self.source=Path(source).resolve()
        self.result=Path(result).resolve();self.checks={};self.images=set();self.finished=False
        self.started=time.monotonic();self.phase='loading';self.start_frames=0;self.ticking=False
        self.original_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.editor.test_mode=True;self.editor.player.setVolume(0)
        self.editor.surface.image_ready.connect(self.frame_ready)
        self.editor.video_loaded.connect(self.loaded)
        self.timer=QTimer(window);self.timer.setInterval(200);self.timer.timeout.connect(self.tick);self.timer.start()
        QTimer.singleShot(300,lambda:self.editor.load_video(self.source))

    def frame_ready(self,image):
        if self.editor.wanted_play and len(self.images)<20:
            small=image.scaled(160,90);bits=small.constBits();bits.setsize(small.byteCount())
            self.images.add(hashlib.sha256(bytes(bits)).hexdigest())

    def loaded(self):
        if self.phase!='loading':return
        self.checks['source_dimensions']=self.editor.info.width>0 and self.editor.info.height>0
        self.phase='original';self.stage_time=time.monotonic()
        # Start thumbnail extraction, then immediately play to reproduce the old race.
        self.editor.request_thumbnail();self.editor.toggle_play()

    def tick(self):
        # Qt multimedia may run a nested event loop while seeking.
        if self.ticking:return
        self.ticking=True
        try:self.advance()
        finally:self.ticking=False

    def advance(self):
        if self.finished:return
        now=time.monotonic();editor=self.editor
        if now-self.started>90:self.finish('预览检查超时');return
        if self.phase=='original' and now-self.stage_time>2:
            self.checks['thumbnail_did_not_stop_play']=editor.wanted_play
            self.phase='proxy-wait'
        if self.phase=='proxy-wait':
            need_proxy=editor.info.width*editor.info.height>1280*720 or float(editor.info.fps)>30
            if need_proxy and (editor.preview_path==editor.info.path or editor.media_seek_pending):return
            self.checks['preview_source']=not need_proxy or (editor.preview_path.is_file() and editor.preview_path!=editor.info.path)
            self.checks['export_source_unchanged']=editor.info.path==self.source
            editor.seek(0);editor.toggle_play();self.start_frames=editor.surface.frame_count
            self.phase='proxy';self.stage_time=now
        elif self.phase=='proxy' and now-self.stage_time>2:
            self.checks['smooth_frames']=editor.surface.frame_count-self.start_frames>=30
            self.checks['moving_frames']=len(self.images)>3
            self.checks['still_playing']=editor.wanted_play and editor.player.position()>500 and not editor.player.error()
            editor.seek(91);self.phase='paused';self.stage_time=now
        elif self.phase=='paused' and now-self.stage_time>1:
            self.checks['exact_seek']=editor.current_frame==91 and not editor.wanted_play and not editor.video_canvas.image.isNull()
            canvas=editor.video_canvas;rect=canvas.painted_rect
            self.checks['fitted_height']=bool(rect and rect.top()<=1 and abs(rect.height()-canvas.height())<=1)
            self.window.splitter.setSizes([900,900]);self.window.resize(1600,950)
            self.phase='resized';self.stage_time=now
        elif self.phase=='resized' and now-self.stage_time>.5:
            canvas=editor.video_canvas;rect=canvas.painted_rect
            self.checks['resize_fit']=bool(rect and rect.top()<=1 and abs(rect.height()-canvas.height())<=1)
            self.checks['source_preserved']=hashlib.sha256(self.source.read_bytes()).hexdigest()==self.original_hash
            self.window.grab().save(str(self.result.with_suffix('.png')))
            self.finish()

    def finish(self,reason=''):
        if self.finished:return
        self.finished=True;self.timer.stop()
        payload={'passed':not reason and all(self.checks.values()),'checks':self.checks,'reason':reason,
                 'rendered_frames':self.editor.surface.frame_count,'distinct_images':len(self.images),
                 'preview':str(self.editor.preview_path),'source':str(self.source),
                 'cursor_frame':self.editor.current_frame,'wanted_play':self.editor.wanted_play}
        if reason:payload['logs']=self.editor.logs.toPlainText()
        self.result.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print(json.dumps(payload,ensure_ascii=False),flush=True)
        self.editor.shutdown_preview();QApplication.instance().exit(0 if payload['passed'] else 1)
