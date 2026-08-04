"""速度数据结构。"""

from dataclasses import dataclass


@dataclass(slots=True)
class Tempo:
    """表示某个节拍位置的速度设置。

    Attributes:
        start_bpm: 起始 BPM。
        end_bpm: 变速目标 BPM，None 表示无变速（恒定速度）。
        duration_beats: 变速持续拍数，0 表示瞬时切换。
    """

    start_bpm: int
    end_bpm: int | None = None
    duration_beats: int = 0

    @property
    def has_ramp(self) -> bool:
        """是否有变速区间（渐快/渐慢）。"""
        return self.end_bpm is not None and self.duration_beats > 0

    def bpm_at_offset(self, offset: int) -> int:
        """获取变速区间内某偏移位置的实际 BPM。

        Args:
            offset: 自该 Tempo 起始拍起的偏移拍数。

        Returns:
            在 offset 处的线性插值 BPM；若 offset 超出区间则返回边界值。
        """
        if not self.has_ramp or offset <= 0 or offset >= self.duration_beats:
            return self.start_bpm
        # if offset <= 0:
        #     return self.start_bpm
        # if offset >= self.duration_beats:
        #     return self.start_bpm
        ratio = offset / self.duration_beats
        return self.start_bpm + (self.end_bpm - self.start_bpm) * ratio

    def to_dict(self) -> dict:
        """导出为可序列化的字典。"""
        d: dict = {"start_bpm": self.start_bpm}
        if self.end_bpm is not None:
            d["end_bpm"] = self.end_bpm
        if self.duration_beats:
            d["duration_beats"] = self.duration_beats
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Tempo":
        """从字典恢复 Tempo 实例。"""
        if isinstance(data, (int, float)):
            return cls(start_bpm=int(data))
        return cls(
            start_bpm=int(data.get("start_bpm", 120)),
            end_bpm=int(data["end_bpm"]) if "end_bpm" in data else None,
            duration_beats=int(data.get("duration_beats", 0)),
        )
