随手一录，轻松一剪。

## Windows 10 / 11 x64

- 新增 Windows 安装版 EXE 和便携 ZIP，内置 Python、Qt、FFmpeg 与 ffprobe，下载后即可使用。
- 使用 Windows 原生屏幕采集，支持主屏、指定屏幕、全桌面及鼠标框选，适配负坐标副屏与显示缩放。
- 支持 F9 开始、F10 停止的全局快捷键；冲突时保留窗口内按键和按钮操作。
- 保留视频剪辑、独立音乐音轨、倍速、撤销重做和 MP4 混音导出。
- Windows 预览使用 Media Foundation，安装包包含 Qt 视频及音频后端；音轨播放错误会显示在日志中。
- 支持导出至不提供硬链接的 Windows 文件系统，并保留同名文件的另存保护。

安装版：下载 `shenlujian-1.2.0-windows-x64-setup.exe`，双击安装；可从开始菜单打开或通过系统卸载。
便携版：完整解压 `shenlujian-1.2.0-windows-x64-portable.zip`，双击其中的 `shenlujian.exe`。

## Linux

继续提供 Ubuntu 22.04 x86_64 的 deb 和 ZIP，保留 X11 及 Wayland 录屏。Wayland 由系统共享对话框选屏，自定义区域手动填写，快捷键在应用窗口内生效。

## 验证与校验

Windows 构建包含原生录屏、视频帧预览、音乐导入与混音导出，以及便携版、安装版和卸载检查；Linux 运行原有回归测试。
GitHub runner 缺少实际音频输出设备时，会明确记录跳过的扬声器播放检查；音轨导入及导出音频解码仍需通过。
各安装包的 SHA-256 摘要见同一 Release 的 `SHA256SUMS`。
