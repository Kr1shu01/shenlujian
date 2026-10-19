# 神录剪

**随手一录，轻松一剪。** Windows / Linux 桌面录屏与音视频剪辑工具，左侧录屏，右侧剪辑。

## 功能

- **录屏**：全屏、指定屏幕或区域录制，自选分辨率与帧率，支持 Windows 及 Linux X11 / Wayland。
- **剪辑**：拖拽排序、删除片段或局部区间、片段与项目倍速、撤销 / 重做。
- **音频**：添加独立音轨，拖动调整起点，与视频原声混合。
- **导出**：MP4；高清保留项目分辨率，标准最高 1080p，省空间最高 720p，保持画面比例。原素材保持不变。

## 安装

### Windows 10 / 11 x64

从 [最新发布页](https://github.com/Kr1shu01/shenlujian/releases/latest) 下载：

- **安装版** `shenlujian-版本-windows-x64-setup.exe`：双击安装，完成后从开始菜单打开「神录剪」。按当前用户安装，无需管理员权限，并提供卸载程序。
- **便携版** `shenlujian-版本-windows-x64-portable.zip`：完整解压后双击 `shenlujian.exe`。保留同目录中的组件文件夹。

两种包都包含 Python、Qt、FFmpeg 和 ffprobe，无需另装运行环境。Windows 使用原生屏幕采集和 F9/F10 全局录屏快捷键，支持多屏及显示缩放。
音乐预览使用 Windows 媒体组件。Windows N/KN 版本需要先启用对应的 Media Feature Pack。

### Linux

适用于 **Ubuntu 22.04（x86_64）**。从 [最新发布页](https://github.com/Kr1shu01/shenlujian/releases/latest) 下载 `.deb`，在下载目录执行：

```bash
sudo apt install ./shenlujian_*_amd64.deb
shenlujian
```

也可从应用菜单打开「神录剪」。首次安装需联网安装依赖。
使用 ZIP 包时，解压后在包目录执行 `bash install.sh`。

## 快速使用

1. **录屏**：左侧选择区域、分辨率和帧率，点击「开始录制」，完成后点击「停止保存」。默认保存到 `~/shenlujian/video/`。
2. **加素材**：右侧点击「添加素材…」或拖入视频、音频；将素材拖到时间线，也可点击「加入时间线」。刚录好的视频可点击「导入最近录屏」。
3. **剪辑**：拖动片段调整顺序；选中片段后，在同一片段内依次双击区间起点和终点，右键「删除选中区间」。整段删除或调整倍速也在右键菜单中。
4. **加音轨**：将音频拖到独立音轨，拖动音频条调整起点；播放预览确认效果。
5. **导出**：填写名称、输出目录，选择清晰度与是否保留视频原声，点击「导出完整项目」。独立音轨始终参与导出。

## 常用操作

- `F9` / `F10`：开始 / 停止录屏。
- `Delete`：删除选中素材或片段；`Ctrl+Z` / `Ctrl+Shift+Z`：撤销 / 重做。
- `←` / `→`：后退 / 前进 5 秒；`Ctrl+滚轮`：缩放时间线。
- `F11`：全屏；`Esc`：返回最大化。

Windows 和 X11 支持全局录屏快捷键；快捷键被其他应用占用时，在应用窗口内使用或点击按钮。Wayland 下快捷键仅在窗口内生效，录屏需通过系统对话框选屏，区域坐标需手动填写。

录屏采集屏幕画面，需要的音乐可在剪辑区加入独立音轨。默认输出目录为当前用户的 `shenlujian/video` 文件夹。

<details>
<summary>源码运行与开发</summary>

系统依赖为 Python 3.10、PyQt5、FFmpeg / GStreamer，安装列表见 [构建配置](.github/workflows/release.yml)。安装依赖后在项目目录执行：

```bash
/usr/bin/python3 -m venv --system-site-packages .build-venv
.build-venv/bin/python shenlujian.py
.build-venv/bin/python -m unittest discover -s tests -t . -v
```

`app/recording/` 录屏 · `app/editor/` 剪辑 · `app/media/` 媒体 · `app/common/` 公共工具 · `tests/` 测试。
打包使用 `bash build_shenlujian.sh`，需在 `.build-venv` 中安装 PyInstaller 6.22.0。

Windows 源码使用 Python 3.11 x64：先运行 `python -m pip install -r requirements-windows.txt`，准备 FFmpeg 并加入 PATH 后运行 `python shenlujian.py`。
原生打包执行 `python build_windows.py --version 1.2.0`，生成安装 EXE 和便携 ZIP。Windows 版由 GitHub Actions 的 Windows runner 构建并验证录屏、预览、混音导出及安装卸载，Linux 继续验证原有功能。
发布包与 `SHA256SUMS` 在两端构建通过后统一上传至 Release。

</details>

[GPL-3.0](LICENSE) · [第三方许可证](licenses/)
