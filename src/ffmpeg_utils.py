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
import os
from pathlib import Path
# import logging
# logger = logging.getLogger(__name__)

# 打包后随 binaries 放到 sys._MEIPASS 下的文件名
if sys.platform == "win32":
    _BUNDLED_FFMPEG_NAME = "ffmpeg.exe"
    _BUNDLED_FFPROBE_NAME = "ffprobe.exe"
else:
    _BUNDLED_FFMPEG_NAME = "ffmpeg"
    _BUNDLED_FFPROBE_NAME = "ffprobe"

# 开发环境候选路径（与 MarchingMap.spec 中 binaries 的来源保持一致）
_DEV_FFMPEG_CANDIDATES = [
    Path(r"C:\ffmpeg-9.0-essentials_build\bin\ffmpeg.exe"),
    Path(r"C:\ffmpeg-9.0-essentials_build\bin\ffprobe.exe"),
]


def _bin_dir() -> Path | None:
    """返回同时包含 ffmpeg.exe 与 ffprobe.exe 的目录。

    优先打包目录（sys._MEIPASS），其次开发候选路径，最后系统 PATH。
    两者必须都存在：pydub 解码/探测音频分别需要 ffmpeg 与 ffprobe。
    """
    def _has_both(directory: Path) -> bool:
        return (
            (directory / _BUNDLED_FFMPEG_NAME).is_file()
            and (directory / _BUNDLED_FFPROBE_NAME).is_file()
        )

    if getattr(sys, "frozen", False):
        bundled_dir = Path(sys._MEIPASS)
        if _has_both(bundled_dir):
            return bundled_dir
    for candidate in _DEV_FFMPEG_CANDIDATES:
        if _has_both(candidate.parent):
            return candidate.parent
    found = shutil.which("ffmpeg")
    if found is None:
        # logger.warning("未找到 ffmpeg")
        return None
    directory = Path(found).parent
    if _has_both(directory):
        return directory
    # logger.warning(f"找到了 ffmpeg 但缺少 ffprobe：{directory}")
    return None


def find_ffmpeg() -> Path | None:
    """定位 ffmpeg.exe：优先打包目录，其次开发候选路径，最后系统 PATH。"""
    directory = _bin_dir()
    if directory is None:
        return None
    return directory / _BUNDLED_FFMPEG_NAME


def find_ffprobe() -> Path | None:
    """定位 ffprobe.exe（pydub 探测音频信息时需要）。"""
    directory = _bin_dir()
    if directory is None:
        return None
    return directory / _BUNDLED_FFPROBE_NAME


def configure_pydub_ffmpeg() -> Path | None:
    """把 pydub 的音频转换器指向找到的 ffmpeg/ffprobe；未找到时返回 None。

    pydub 除了用 ffmpeg 转换，还会用 ffprobe（get_prober_name 从 PATH 查找）
    探测文件信息，因此这里同时配置 AudioSegment.converter / prober，并把
    ffmpeg/ffprobe 所在目录前置到 PATH，保证打包后（不在系统 PATH 中）也能工作。
    """
    directory = _bin_dir()
    if directory is None:
        return None
    try:
        from pydub import AudioSegment

        ffmpeg = directory / _BUNDLED_FFMPEG_NAME
        ffprobe = directory / _BUNDLED_FFPROBE_NAME
        AudioSegment.converter = str(ffmpeg)
        AudioSegment.prober = str(ffprobe)
        # 让 pydub 内部的 get_prober_name()/which() 也能在打包目录找到 ffmpeg/ffprobe
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
        # logger.info(f"已配置 pydub 的 ffmpeg 转换器：{ffmpeg}")
    except Exception as e:
        # logger.warning(f"无法配置 pydub 的 ffmpeg 转换器\n{e}")
        return None
    return ffmpeg
