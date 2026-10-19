"""Frame-based project sequence; source files are never modified."""
from dataclasses import dataclass,replace
from fractions import Fraction
import colorsys,hashlib,math,uuid
from app.media.video_sizes import export_size


def source_color(path):
    hue=int.from_bytes(hashlib.sha256(str(path).encode()).digest()[:2],'big')/65536
    rgb=colorsys.hsv_to_rgb(hue,.46,.40)
    return '#'+''.join(f'{round(channel*255):02x}' for channel in rgb)


@dataclass(frozen=True)
class Clip:
    uid: str
    info: object
    start: int
    end: int
    speed: float=1.0
    color: str=''
    output_start: int=0
    output_end: object=None
    offset: int=0
    @property
    def retimed_frames(self):return max(1,round((self.end-self.start)/self.speed))
    @property
    def stop(self):return self.retimed_frames if self.output_end is None else self.output_end
    @property
    def frames(self):return self.stop-self.output_start
    def source_position(self,frame):return min(self.end,self.start+(self.output_start+frame)*self.speed)
    def source_frame(self,frame):return min(self.end-1,max(self.start,math.floor(self.source_position(frame)+1e-8)))
    def timeline_frame(self,source_frame):return (source_frame-self.start)/self.speed-self.output_start
    def slice(self,a,b):
        if self.speed==1:
            return replace(self,start=round(self.source_position(a)),end=round(self.source_position(b)),output_start=0,output_end=None)
        return replace(self,output_start=self.output_start+a,output_end=self.output_start+b)


class Project:
    def __init__(self):
        self.clips=[];self.audio_clips=[];self.fps=None;self.width=0;self.height=0;self.history=[];self.future=[]
    @property
    def video_frames(self):return sum(clip.frames for clip in self.clips)
    @property
    def frames(self):return max(self.video_frames,max((c.offset+c.frames for c in self.audio_clips),default=0))
    def get_clip(self,uid):return next((c for c in self.clips+self.audio_clips if c.uid==uid),None)
    @property
    def duration(self):return self.frames/float(self.fps) if self.fps else 0
    def snapshot(self):return (list(self.clips),list(self.audio_clips),self.fps,self.width,self.height)
    def restore(self,state):self.clips,self.audio_clips,self.fps,self.width,self.height=list(state[0]),list(state[1]),*state[2:]
    def checkpoint(self):self.history.append(self.snapshot());self.future.clear()

    def insert(self,infos,index=None):
        if not infos:return []
        self.checkpoint()
        if not self.fps:self.fps=infos[0].fps
        if not self.clips:self.width=infos[0].width//2*2;self.height=infos[0].height//2*2
        clips=[Clip(uuid.uuid4().hex,info,0,max(1,round(info.duration*float(self.fps))),color=source_color(info.path)) for info in infos]
        index=len(self.clips) if index is None else max(0,min(len(self.clips),index))
        self.clips[index:index]=clips;return clips

    def offset(self,index):return sum(clip.frames for clip in self.clips[:index])
    def locate(self,frame):
        if not self.clips:return None
        frame=max(0,min(self.video_frames-1,int(frame)));offset=0
        for index,clip in enumerate(self.clips):
            if frame<offset+clip.frames:return index,clip,clip.source_frame(frame-offset),offset
            offset+=clip.frames

    def move(self,uid,insertion):
        old=next((i for i,c in enumerate(self.clips) if c.uid==uid),None)
        if old is None:return False
        target=max(0,min(len(self.clips),insertion))
        if target>old:target-=1
        if target==old:return False
        self.checkpoint();clip=self.clips.pop(old);self.clips.insert(target,clip);return True

    def insert_audio(self,infos,frame=0):
        if not infos:return []
        self.checkpoint()
        if not self.fps:self.fps=Fraction(30)
        clips=[]
        for info in infos:
            clip=Clip(uuid.uuid4().hex,info,0,max(1,round(info.duration*float(self.fps))),color=source_color(info.path),offset=max(0,int(frame)))
            clips.append(clip);frame=clip.offset+clip.frames
        self.audio_clips.extend(clips);return clips

    def move_audio(self,uid,frame):
        index=next((i for i,c in enumerate(self.audio_clips) if c.uid==uid),None)
        if index is None:return False
        frame=max(0,int(frame))
        if frame==self.audio_clips[index].offset:return False
        self.checkpoint();self.audio_clips[index]=replace(self.audio_clips[index],offset=frame);return True

    def delete_clip(self,uid):
        for track in (self.clips,self.audio_clips):
            index=next((i for i,c in enumerate(track) if c.uid==uid),None)
            if index is not None:self.checkpoint();track.pop(index);return True
        return False

    def set_clip_speed(self,uid,speed):
        from app.editor.operations import tempo_chain
        tempo_chain(speed)
        if not .1<=speed<=16:raise ValueError('片段倍速须为 0.1 至 16 倍。')
        track=self.audio_clips if any(c.uid==uid for c in self.audio_clips) else self.clips
        index=next((i for i,c in enumerate(track) if c.uid==uid),None)
        if index is None or track[index].speed==speed:return False
        clip=track[index];new=replace(clip,speed=speed,output_start=0,output_end=None)
        a=max(0,min(new.retimed_frames-1,round(clip.output_start*clip.speed/speed)))
        b=max(a+1,min(new.retimed_frames,round(clip.stop*clip.speed/speed)))
        self.checkpoint();track[index]=replace(new,output_start=a,output_end=b);return True

    def delete_clip_range(self,uid,start,end):
        track=self.audio_clips if any(c.uid==uid for c in self.audio_clips) else self.clips
        index=next((i for i,c in enumerate(track) if c.uid==uid),None)
        if index is None:return False
        clip=track[index];offset=clip.offset if track is self.audio_clips else self.offset(index)
        if not offset<=start<end<=offset+clip.frames:return False
        a,b=start-offset,end-offset;parts=[]
        if a:parts.append(clip.slice(0,a))
        if b<clip.frames:
            right=clip.slice(b,clip.frames)
            parts.append(replace(right,uid=uuid.uuid4().hex if a else clip.uid,
                                 offset=offset+a if track is self.audio_clips else clip.offset))
        self.checkpoint();track[index:index+1]=parts;return True

    def delete_range(self,start,end):
        if not 0<=start<end<=self.frames:raise ValueError('选区超出项目范围。')
        self.checkpoint();updated=[];offset=0
        for clip in self.clips:
            finish=offset+clip.frames;a=max(start,offset);b=min(end,finish)
            if a>=b:updated.append(clip)
            else:
                if a>offset:updated.append(clip.slice(0,a-offset))
                if b<finish:
                    right=clip.slice(b-offset,clip.frames)
                    updated.append(replace(right,uid=uuid.uuid4().hex if a>offset else clip.uid))
            offset=finish
        self.clips=updated;audio=[]
        for clip in self.audio_clips:
            finish=clip.offset+clip.frames
            if finish<=start:audio.append(clip)
            elif clip.offset>=end:audio.append(replace(clip,offset=clip.offset-(end-start)))
            else:
                left=max(0,start-clip.offset);right=min(clip.frames,end-clip.offset)
                if left:audio.append(clip.slice(0,left))
                if right<clip.frames:
                    audio.append(replace(clip.slice(right,clip.frames),uid=uuid.uuid4().hex if left else clip.uid,offset=start))
        self.audio_clips=audio

    def clear(self):
        if not self.clips and not self.audio_clips and self.fps is None:return False
        self.checkpoint();self.clips=[];self.audio_clips=[];self.fps=None;self.width=self.height=0;return True
    def undo(self):
        if not self.history:return False
        self.future.append(self.snapshot());self.restore(self.history.pop());return True
    def redo(self):
        if not self.future:return False
        self.history.append(self.snapshot());self.restore(self.future.pop());return True


def project_export_arguments(project,destination,speed=1,crf=23,audio=True):
    from app.editor.operations import tempo_chain
    if not project.frames:raise ValueError('请先把素材加入时间线。')
    tempo=tempo_chain(speed)
    if not 0<=crf<=35:raise ValueError('导出清晰度无效。')
    rate=f'{project.fps.numerator}/{project.fps.denominator}';fps=float(project.fps)
    width,height=export_size(project.width or 1920,project.height or 1080,crf)
    original=audio and any(c.info.audio for c in project.clips)
    include_audio=original or bool(project.audio_clips)
    args=['-hide_banner','-loglevel','warning','-n'];graph=[]
    for i,clip in enumerate(project.clips):
        args+=['-threads','2','-i',str(clip.info.path)]
        graph.append(f'[{i}:v:0]fps={rate},trim=start_frame={clip.start}:end_frame={clip.end},setpts=N/({rate}*{clip.speed:.12g}*TB),'
                     f'tpad=stop_mode=clone:stop_duration={1/fps:.9f},fps={rate}:eof_action=pass,'
                     f'trim=start_frame={clip.output_start}:end_frame={clip.stop},setpts=N/({rate}*TB),'
                     f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                     f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,settb=AVTB[v{i}]')
        if original:
            length=clip.frames/fps
            if clip.info.audio:
                graph.append(f'[{i}:a:0]atrim=start={clip.start/fps:.9f}:end={clip.end/fps:.9f},asetpts=PTS-STARTPTS,'
                             f'aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
                             f'{tempo_chain(clip.speed)},atrim=start={clip.output_start/fps:.9f}:end={clip.stop/fps:.9f},asetpts=PTS-STARTPTS,'
                             f'apad=whole_dur={length:.9f},atrim=duration={length:.9f}[a{i}]')
            else:graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={length:.9f},asetpts=PTS-STARTPTS[a{i}]')
    if project.clips:
        streams=''.join(f'[v{i}]'+(f'[a{i}]' if original else '') for i in range(len(project.clips)))
        graph.append(streams+f'concat=n={len(project.clips)}:v=1:a={int(original)}[joinedv]'+('[joineda]' if original else ''))
    else:graph.append(f'color=c=black:s={width}x{height}:r={rate}:d={project.duration:.9f}[joinedv]')
    tail=max(0,project.frames-project.video_frames)/fps
    graph.append(f'[joinedv]setpts=N/({rate}*{speed:.12g}*TB),tpad=stop_mode=clone:stop_duration={(tail+1/fps)/speed:.9f},fps={rate}:eof_action=pass[outv]')
    audio_labels=[]
    if original:
        graph.append(f'[joineda]apad=whole_dur={project.duration:.9f},atrim=duration={project.duration:.9f}[original]');audio_labels.append('[original]')
    for j,clip in enumerate(project.audio_clips):
        i=len(project.clips)+j;args+=['-threads','2','-i',str(clip.info.path)]
        graph.append(f'[{i}:a:0]atrim=start={clip.start/fps:.9f}:end={clip.end/fps:.9f},asetpts=PTS-STARTPTS,'
                     f'aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
                     f'{tempo_chain(clip.speed)},atrim=start={clip.output_start/fps:.9f}:end={clip.stop/fps:.9f},asetpts=PTS-STARTPTS,'
                     f'apad=whole_dur={clip.frames/fps:.9f},atrim=duration={clip.frames/fps:.9f},'
                     f'adelay={round(clip.offset/fps*48000)}S:all=1,asetpts=N/SR/TB,'
                     f'apad=whole_dur={project.duration:.9f},atrim=duration={project.duration:.9f}[extra{j}]')
        audio_labels.append(f'[extra{j}]')
    if include_audio:
        graph.append(''.join(audio_labels)+f'amix=inputs={len(audio_labels)}:duration=longest:normalize=0:dropout_transition=0,alimiter=limit=0.95:level=0:attack=1:release=10,{tempo}[outa]')
    args+=['-filter_complex_threads','2','-filter_complex',';'.join(graph),'-map','[outv]']
    if include_audio:args+=['-map','[outa]','-c:a','aac','-b:a','192k']
    else:args+=['-an']
    duration=project.duration/speed
    args+=['-c:v','libx264','-crf',str(crf),'-preset','veryfast','-pix_fmt','yuv420p','-threads','4',
           '-t',f'{duration:.9f}','-movflags','+faststart','-progress','pipe:1','-stats_period','0.5','-f','mp4',str(destination)]
    return args,duration
