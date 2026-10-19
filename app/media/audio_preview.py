"""Synchronize the independent audio track with the project transport."""
import math
from PyQt5.QtCore import QObject,QTimer,QUrl,pyqtSignal
from PyQt5.QtMultimedia import QMediaContent,QMediaPlayer


class AudioPreview(QObject):
    error=pyqtSignal(str)
    def __init__(self,parent,project):
        super().__init__(parent);self.project=project;self.players={};self.muted=False
    def prune(self):
        ids={c.uid for c in self.project.audio_clips}
        for uid in list(self.players):
            if uid not in ids:
                entry=self.players.pop(uid);entry['player'].stop();entry['player'].setMedia(QMediaContent());entry['player'].deleteLater()
    def ready(self,entry,status):
        if status==QMediaPlayer.LoadingMedia:entry['pending']=True
        elif status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia) and entry['pending']:
            entry['pending']=False;player=entry['player'];player.setPosition(entry['position']);player.setPlaybackRate(entry['rate'])
            if entry['play']:QTimer.singleShot(0,lambda:player.play() if entry['play'] else None)
    def sync(self,frame,playing,global_speed,fps,force=False):
        self.prune()
        for clip in self.project.audio_clips:
            active=clip.offset<=frame<clip.offset+clip.frames;entry=self.players.get(clip.uid)
            position=math.ceil(clip.source_position(max(0,frame-clip.offset) if active else 0)/float(fps)*1000-1e-9)
            if entry is None:
                player=QMediaPlayer(self);player.setNotifyInterval(20)
                entry={'player':player,'pending':True,'position':position,'rate':clip.speed*global_speed,'play':playing and active}
                self.players[clip.uid]=entry;player.mediaStatusChanged.connect(lambda status,e=entry:self.ready(e,status))
                player.error.connect(lambda code,p=player,c=clip:self.error.emit(c.info.path.name+'：'+(p.errorString() or '音频播放失败，请检查输出设备和媒体解码支持。')) if code else None)
                player.setMedia(QMediaContent(QUrl.fromLocalFile(str(clip.info.path))));player.pause()
            if not active:
                entry['play']=False;entry['player'].pause();continue
            entry['position']=position;entry['rate']=clip.speed*global_speed;entry['play']=playing
            player=entry['player'];player.setMuted(self.muted)
            if entry['pending']:continue
            player.setPlaybackRate(entry['rate'])
            if force or abs(player.position()-position)>180 or player.mediaStatus()==QMediaPlayer.EndOfMedia:player.setPosition(position)
            if playing:player.play() if player.state()!=QMediaPlayer.PlayingState else None
            else:player.pause()
    def stop(self):
        for entry in self.players.values():entry['play']=False;entry['player'].pause()
    def shutdown(self):
        for entry in self.players.values():entry['play']=False;entry['player'].stop();entry['player'].setMedia(QMediaContent());entry['player'].deleteLater()
        self.players.clear()
