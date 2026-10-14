"""Normalize and concatenate complete videos into one MP4."""
import math


def concatenate_arguments(infos,destination,crf=23,audio=True):
    if len(infos)<2:raise ValueError('请至少加入两个视频。')
    if not 0<=crf<=35:raise ValueError('导出清晰度无效。')
    first=infos[0];width=first.width-first.width%2;height=first.height-first.height%2
    if min(width,height)<2:raise ValueError('视频尺寸无效。')
    rate=f'{first.fps.numerator}/{first.fps.denominator}'
    include_audio=audio and any(info.audio for info in infos)
    arguments=['-hide_banner','-loglevel','warning','-n']
    graph=[];duration=0
    for index,info in enumerate(infos):
        if not math.isfinite(info.duration) or info.duration<=0:raise ValueError('视频时长无效。')
        length=info.duration;duration+=length
        arguments+=['-threads','2','-i',str(info.path)]
        graph.append(f'[{index}:v:0]setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                     f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={rate},trim=duration={length:.9f},'
                     f'settb=AVTB,setpts=PTS-STARTPTS[v{index}]')
        if include_audio:
            if info.audio:
                graph.append(f'[{index}:a:0]aresample=48000:async=1:first_pts=0,'
                             f'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
                             f'apad=whole_dur={length:.9f},atrim=duration={length:.9f},asetpts=PTS-STARTPTS[a{index}]')
            else:
                graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={length:.9f},asetpts=PTS-STARTPTS[a{index}]')
    streams=''.join(f'[v{i}]'+(f'[a{i}]' if include_audio else '') for i in range(len(infos)))
    graph.append(streams+f'concat=n={len(infos)}:v=1:a={int(include_audio)}[outv]'+('[outa]' if include_audio else ''))
    arguments+=['-filter_complex_threads','2','-filter_complex',';'.join(graph),'-map','[outv]']
    if include_audio:arguments+=['-map','[outa]','-c:a','aac','-b:a','192k']
    else:arguments+=['-an']
    arguments+=['-c:v','libx264','-crf',str(crf),'-preset','veryfast','-pix_fmt','yuv420p','-threads','4',
                '-t',f'{duration:.9f}','-movflags','+faststart','-progress','pipe:1','-stats_period','0.5',
                '-f','mp4',str(destination)]
    return arguments,duration
