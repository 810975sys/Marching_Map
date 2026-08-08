"""音频数据模型与波形处理。

- AudioSegment: 一个“音频段”（剪辑）。非破坏式设计，只记录源文件路径与
  源文件内的截取区间 [src_start, src_end]（秒），以及它在时间轴上的起始拍
  start_beat（锚点）。拍位→秒的轴对齐映射由 TimelineWidget 依据 beat_tempo
  动态计算（变速区间内每拍取该拍起始 BPM，与播放进度计算一致），因此改 BPM
  后波形显示与播放会按节拍自动重新对齐。
- 波形峰值缓存：用 pydub 解码为单声道 22050Hz float32，并按桶(min/max)预计算，
  绘制时按 (文件, 源区间) 切片，速度快且可随时间轴缩放平滑重绘。
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# 波形解码参数：单声道 22050Hz 已足够绘制波形，同时控制内存占用。
SAMPLE_RATE = 22050
# 峰值桶大小（采样点数），约 256/22050 ≈ 11.6ms，细于最小缩放下的单个像素。
BUCKET = 256

# 文件路径 -> (sample_rate, mono float32 归一化采样)
_WAVEFORM_CACHE: dict[str, tuple[int, np.ndarray]] = {}
# 文件峰值缓存：键 (path, bucket) -> min/max 峰值数组，避免每次绘制重复分桶计算。
# 与 _WAVEFORM_CACHE 一样假设源文件在会话内不可变。
_PEAKS_CACHE: dict[tuple[str, int], np.ndarray] = {}


def _decode(path: str) -> tuple[int, np.ndarray] | None:
    """解码音频文件为单声道 22050Hz float32（[-1, 1]），结果按路径缓存。"""
    cached = _WAVEFORM_CACHE.get(path)
    if cached is not None:
        return cached
    try:
        from pydub import AudioSegment

        seg = AudioSegment.from_file(path)
        seg = seg.set_channels(1)
        seg = seg.set_frame_rate(SAMPLE_RATE)
        samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
        samples = samples / 32768.0
        _WAVEFORM_CACHE[path] = (SAMPLE_RATE, samples)
        return _WAVEFORM_CACHE[path]
    except Exception:
        return None


def audio_duration(path: str) -> float:
    """返回音频文件时长（秒）；无法读取时返回 0。"""
    info = _decode(path)
    if info is None:
        return 0.0
    sr, samples = info
    return len(samples) / float(sr)


def get_file_peaks(path: str, bucket: int = BUCKET) -> np.ndarray | None:
    """返回整个文件的 min/max 峰值数组，形状 (N, 2)，按 (路径, 桶大小) 缓存。"""
    key = (path, bucket)
    cached = _PEAKS_CACHE.get(key)
    if cached is not None:
        return cached
    info = _decode(path)
    if info is None:
        return None
    samples = info[1]
    n = len(samples)
    if n <= 0:
        return None
    nb = (n + bucket - 1) // bucket
    pad = nb * bucket - n
    a = samples
    if pad:
        a = np.concatenate([a, np.zeros(pad, dtype=np.float32)])
    a2 = a.reshape(nb, bucket)
    mn = a2.min(axis=1)
    mx = a2.max(axis=1)
    peaks = np.stack([mn, mx], axis=1)
    _PEAKS_CACHE[key] = peaks
    return peaks


def get_range_peaks(path: str, t0: float, t1: float, bucket: int = BUCKET) -> np.ndarray | None:
    """返回源文件 [t0, t1]（秒）区间对应的 min/max 峰值数组。"""
    peaks = get_file_peaks(path, bucket)
    if peaks is None:
        return None
    i0 = max(0, int(t0 * SAMPLE_RATE) // bucket)
    i1 = min(len(peaks), int(t1 * SAMPLE_RATE) // bucket + 1)
    if i1 <= i0:
        return None
    return peaks[i0:i1]


@dataclass
class AudioSegment:
    """一个音频段（剪辑）。

    Attributes:
        file: 源音频文件路径（内存中为绝对路径；to_dict 序列化时统一为绝对路径）。
        src_start: 源文件内截取起点（秒）。
        src_end: 源文件内截取终点（秒）。
        start_beat: 时间轴上起始拍（可为浮点，锚点）。

    结束拍 end_beat 与拍位↔源时间的映射由 TimelineWidget 依据 beat_tempo 计算
    （见 timeline_widget.audio_segment_end_beat / _audio_source_time_at_beat），
    不在此固化，以保证轴对齐始终跟随节拍速度。
    """

    file: str
    src_start: float = 0.0
    src_end: float = 0.0
    start_beat: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """截取区间时长（秒）。"""
        return max(0.0, self.src_end - self.src_start)

    def to_dict(self) -> dict:
        """导出段数据；file 统一为绝对路径，保证方案保存后可恢复。"""
        return {
            "file": self.resolve_file(),
            "src_start": round(self.src_start, 3),
            "src_end": round(self.src_end, 3),
            "start_beat": round(self.start_beat, 3),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AudioSegment":
        return cls(
            file=str(data.get("file", "")),
            src_start=float(data.get("src_start", 0.0)),
            src_end=float(data.get("src_end", 0.0)),
            start_beat=float(data.get("start_beat", 0.0)),
        )

    def resolve_file(self) -> str:
        """返回可用于读取的绝对路径。"""
        return str(Path(self.file).resolve())
