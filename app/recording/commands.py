"""Validated screen-recording options and shell-free FFmpeg commands."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from app.media.video_sizes import even_size


@dataclass(frozen=True)
class RecordingOptions:
    display: str
    x: int
    y: int
    width: int
    height: int
    fps: int = 30
    crf: int = 23
    preset: str = "ultrafast"
    output_width: int = 0
    output_height: int = 0
    cursor: bool = True

    def validate(self):
        if not self.display:
            raise ValueError("未检测到 DISPLAY，请在 X11 桌面中打开应用。")
        if min(self.x, self.y) < 0 or min(self.width, self.height) < 2:
            raise ValueError("录制区域的坐标和尺寸无效。")
        if not 1 <= self.fps <= 120:
            raise ValueError("帧率应在 1–120 之间。")
        if not 0 <= self.crf <= 35:
            raise ValueError("清晰度参数应在 0–35 之间。")
        if self.preset not in {"ultrafast", "superfast", "veryfast", "fast", "medium"}:
            raise ValueError("编码速度选项无效。")
        if bool(self.output_width) != bool(self.output_height):
            raise ValueError("请同时填写输出宽度和高度。")
        if self.output_width and min(self.output_width, self.output_height) < 2:
            raise ValueError("输出尺寸至少为 2×2。")

    @property
    def video_size(self):
        width = self.output_width or self.width
        height = self.output_height or self.height
        return even_size(width,height)


def output_path(directory: str, name: str, timestamp: bool, now=None):
    name = name.strip()
    if name.lower().endswith(".mp4"):
        name = name[:-4]
    if not name or name in {".", ".."} or any(c in name for c in ("/", "\\", "\x00", "\n", "\r")):
        raise ValueError("请填写视频名称，不要包含路径或换行。")
    if timestamp:
        name += "_" + (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    folder = Path(directory).expanduser()
    if not folder.is_absolute():
        raise ValueError("请选择完整的输出目录。")
    candidate = folder / (name + ".mp4")
    counter = 1
    while candidate.exists():
        candidate = folder / f"{name}_{counter:03d}.mp4"
        counter += 1
    return candidate


def ffmpeg_arguments(options: RecordingOptions, destination: Path):
    options.validate()
    width, height = options.video_size
    return [
        "-hide_banner", "-loglevel", "warning", "-n",
        "-video_size", f"{options.width}x{options.height}",
        "-framerate", str(options.fps), "-f", "x11grab",
        "-draw_mouse", "1" if options.cursor else "0",
        "-probesize", "32", "-analyzeduration", "0",
        "-i", f"{options.display}+{options.x},{options.y}",
        "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
                 f"force_divisible_by=2:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"),
        "-c:v", "libx264", "-preset", options.preset,
        "-crf", str(options.crf), "-pix_fmt", "yuv420p",
        "-threads", "4", "-movflags", "+faststart",
        "-progress", "pipe:1", "-stats_period", "0.5", str(destination),
    ]
