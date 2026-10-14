"""Frame-based cuts, speed changes, and FFmpeg export for 神录剪."""
from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: Fraction
    frames: int
    duration: float
    audio: bool

    @classmethod
    def from_probe(cls, path, payload):
        streams = payload.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
        if video is None:
            raise ValueError("文件中没有可剪辑的视频轨道。")
        try:
            fps = Fraction(video.get("avg_frame_rate", "0/1"))
            if fps <= 0: fps = Fraction(video.get("r_frame_rate", "0/1"))
            duration = float(video.get("duration") or payload.get("format", {}).get("duration") or 0)
            frames = int(video.get("nb_frames") or video.get("nb_read_frames") or round(duration * float(fps)))
        except (ValueError, ZeroDivisionError, TypeError) as error:
            raise ValueError("无法读取视频的帧率或时长。") from error
        if fps <= 0 or frames <= 0 or not math.isfinite(duration):
            raise ValueError("视频帧率或时长无效。")
        if duration <= 0: duration = frames / float(fps)
        return cls(Path(path), int(video["width"]), int(video["height"]), fps, frames, duration,
                   any(s.get("codec_type") == "audio" for s in streams))


def merge_cuts(cuts, total_frames):
    normalized = []
    for start, end in cuts:
        if not (0 <= start < end <= total_frames):
            raise ValueError("删除区间超出视频帧范围。")
        normalized.append((int(start), int(end)))
    merged = []
    for start, end in sorted(normalized):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def kept_ranges(total_frames, start, end, cuts):
    if not 0 <= start < end <= total_frames:
        raise ValueError("请设置有效的保留范围，开始帧应不大于结束帧。")
    result = []
    cursor = start
    for cut_start, cut_end in merge_cuts(cuts, total_frames):
        if cut_end <= start: continue
        if cut_start >= end: break
        if cut_start > cursor: result.append((cursor, min(cut_start, end)))
        cursor = max(cursor, cut_end)
        if cursor >= end: break
    if cursor < end: result.append((cursor, end))
    if not result: raise ValueError("没有剩余画面，请调整删除区间或保留范围。")
    return result


def tempo_chain(speed):
    if not math.isfinite(speed) or not .1 <= speed <= 16:
        raise ValueError("倍速应在 0.1–16 之间。")
    factors = []
    remaining = speed
    while remaining > 2:
        factors.append(2.0); remaining /= 2
    while remaining < .5:
        factors.append(.5); remaining /= .5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.12g}" for factor in factors)


def export_arguments(info, destination, start, end, cuts, speed=1.0, crf=23, audio=True):
    ranges = kept_ranges(info.frames, start, end, cuts)
    tempo = tempo_chain(speed)
    if not 0 <= crf <= 35: raise ValueError("导出清晰度无效。")
    include_audio = audio and info.audio
    count = len(ranges)
    rate = f"{info.fps.numerator}/{info.fps.denominator}"
    expression = "+".join(f"between(n\\,{first}\\,{last-1})" for first,last in ranges)
    graph = [f"[0:v:0]select='{expression}',setpts=N/({rate}*{speed:.12g}*TB),"
             f"tpad=stop_mode=clone:stop_duration={1 / float(info.fps) / speed:.9f},"
             f"fps=fps={rate}:eof_action=pass,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[outv]"]
    if include_audio:
        if count > 1: graph.append(f"[0:a:0]asplit={count}" + "".join(f"[as{i}]" for i in range(count)))
        for index,(first,last) in enumerate(ranges):
            audio_in = f"as{index}" if count > 1 else "0:a:0"
            begin = first / float(info.fps)
            finish = last / float(info.fps)
            length = finish - begin
            graph.append(f"[{audio_in}]atrim=start={begin:.9f}:end={finish:.9f},asetpts=PTS-STARTPTS,"
                         f"apad=whole_dur={length:.9f},atrim=duration={length:.9f}[a{index}]")
        graph.append("".join(f"[a{i}]" for i in range(count)) + f"concat=n={count}:v=0:a=1[joineda]")
        graph.append(f"[joineda]{tempo}[outa]")
    duration = sum(b-a for a,b in ranges) / float(info.fps) / speed
    arguments = ["-hide_banner", "-loglevel", "warning", "-n", "-i", str(info.path),
                 "-filter_complex", ";".join(graph), "-map", "[outv]"]
    if include_audio: arguments += ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
    else: arguments += ["-an"]
    arguments += ["-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast", "-pix_fmt", "yuv420p",
                  "-threads", "4", "-t", f"{duration:.9f}", "-movflags", "+faststart", "-progress", "pipe:1",
                  "-stats_period", "0.5", "-f", "mp4", str(destination)]
    return arguments, duration, ranges
