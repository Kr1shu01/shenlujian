"""Video and standalone audio metadata for the shared asset library."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import math
from app.editor.operations import VideoInfo


@dataclass(frozen=True)
class AudioInfo:
    path: Path
    duration: float
    audio: bool=True
    width: int=0
    height: int=0
    fps: Fraction=Fraction(30)
    @property
    def frames(self):return max(1,round(self.duration*30))
    @property
    def has_video(self):return False

    @classmethod
    def from_probe(cls,path,payload):
        stream=next((s for s in payload.get('streams',[]) if s.get('codec_type')=='audio'),None)
        if stream is None:raise ValueError('文件中没有可读取的视频或音频。')
        duration=0
        for value in (stream.get('duration'),payload.get('format',{}).get('duration')):
            try:candidate=float(value)
            except (ValueError,TypeError):continue
            if math.isfinite(candidate) and candidate>0:duration=candidate;break
        if duration<=0:raise ValueError('音频时长无效。')
        return cls(Path(path),duration)


def probe_media(path,payload):
    video=any(s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic') for s in payload.get('streams',[]))
    return VideoInfo.from_probe(path,payload) if video else AudioInfo.from_probe(path,payload)
