"""ffmpeg 定位与 pydub 转换器配置。

打包后（PyInstaller onedir）ffmpeg.exe 由 MarchingMap.spec 的 binaries
放入 sys._MEIPASS（即 dist/MarchingMap/_internal/）目录；开发环境下按
候选路径或系统 PATH 查找。启动时调用 configure_pydub_ffmpeg() 把 pydub 的
AudioSegment.converter 指向该 ffmpeg，避免打包后因系统 PATH 中没有
ffmpeg 而无法解码/导出音频。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# 打包后随 binaries 放到 sys._MEIPASS 下的文件名
_BUNDLED_FFMPEG_NAME = "ffmpeg.exe"

# 开发环境候选路径（与 MarchingMap.spec 中 binaries 的来源保持一致）
_DEV_FFMPEG_CANDIDATES = [
    Path(r"C:\\ffmpeg-9.0-essentials_build\\bin\\ffmpeg.exe"),
]


def find_ffmpeg() -> Path | None:
    """定位 ffmpeg.exe：优先打包目录，其次开发候选路径，最后系统 PATH。"""
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / _BUNDLED_FFMPEG_NAME
        if bundled.is_file():
            return bundled
    for candidate in _DEV_FFMPEG_CANDIDATES:
        if candidate.is_file():
            return candidate
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def configure_pydub_ffmpeg() -> Path | None:
    """把 pydub 的音频转换器指向找到的 ffmpeg；未找到时返回 None。"""
    path = find_ffmpeg()
    if path is None:
        return None
    try:
        from pydub import AudioSegment

        AudioSegment.converter = str(path)
    except Exception:
        return None
    return path
