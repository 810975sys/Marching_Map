"""撤销 / 重做管理器（快照式）。

设计要点
--------
- 每步操作保存一份“操作前”的完整状态快照（场景 + 时间轴 + 场地/应用设置 + UI 状态）。
- 撤销/重做通过“恢复快照”实现，天然支持“先清冲突路径再写新路径”等复杂语义——
  只要把节点删/改前后整体快照还原，冲突信息与新增信息都会被正确恢复。
- 会话（begin/commit/cancel）：绘制、分组、标签、文本框、箭头、路径、拖拽等从
  “工具进入 / 按下鼠标”到“确认 / 松开鼠标”之间的所有中间修改合并为一步。
  快照在 begin（工具进入、尚未产生任何已确认数据修改）时捕获，因此撤销后能恢复到
  “点击按钮进入该绘图方式时的状态”。
- 设置合并（notify_param_change）：同一参数连续多次修改合并为一步；切换参数时把
  上一个参数的修改作为独立一步入栈。
"""

import copy


class HistoryManager:
    """统一的撤销/重做历史栈。

    capture: () -> snapshot，采集当前完整状态（含 UI 状态）。
    restore: (snapshot) -> None，把快照恢复到各数据层并刷新界面。
    max_steps: 撤销栈保留的步数上限（超出丢弃最旧）。
    on_changed: 可选回调，撤销/重做/入栈状态变化时触发（用于刷新菜单可用性）。
    """

    def __init__(self, capture, restore, max_steps: int = 50, on_changed=None):
        self._capture = capture
        self._restore = restore
        self._max_steps = max(1, int(max_steps))
        self._on_changed = on_changed
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self._session = None          # (label, before_snapshot)：进行中的会话
        self._merge_key = None        # 当前正在合并的“同一参数”键
        self._merge_snapshot = None   # 该参数首次修改前的快照
        self._restoring = False       # 正在恢复快照（禁止再记录）

    # ────────────── 生命周期 ──────────────
    def initialize(self):
        """清空全部历史（新建 / 打开方案后调用），使当前状态成为新的基准。"""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._session = None
        self._merge_key = None
        self._merge_snapshot = None
        self._notify_changed()

    # ────────────── 会话（绘制 / 拖拽等）──────────────
    def begin(self, label: str = "编辑"):
        """开始一个会话：先结束上一个未完成会话、提交待合并的设置，再快照当前状态。"""
        if self._restoring:
            return
        self._discard_session()
        self._flush_merge()
        self._session = (label, self._capture())

    def commit(self):
        """确认会话：把 begin 时捕获的“操作前”快照入栈为一步。"""
        if self._restoring:
            return
        if self._session is None:
            return
        _, before = self._session
        self._session = None
        self._push(before)

    def cancel(self):
        """取消会话：丢弃 begin 时捕获的快照（不产生撤销步骤）。"""
        if self._restoring:
            return
        self._session = None

    def has_active_session(self) -> bool:
        """当前是否存在未确认的会话（begin 后尚未 commit/cancel）。"""
        return self._session is not None

    def record_op(self, fn):
        """一次性操作：执行前快照，执行后整体入栈为一步。返回 fn 的返回值。"""
        if self._restoring:
            return fn()
        self._discard_session()
        self._flush_merge()
        before = self._capture()
        result = fn()
        self._push(before)
        return result

    # ────────────── 设置合并 ──────────────
    def notify_param_change(self, key: str):
        """通知某一参数即将被修改。

        同一 key 连续修改合并为一步；切换到新 key 时，把上一个 key 的修改作为
        独立一步入栈，并为新 key 记录“修改前”快照。
        """
        if self._restoring:
            return
        if self._merge_key == key:
            return
        if self._merge_key is not None:
            # 上一个参数的修改已结束 → 作为一步操作提交（同时清除重做栈）
            self._push(self._merge_snapshot)
        self._merge_key = key
        self._merge_snapshot = self._capture()

    # ────────────── 撤销 / 重做 ──────────────
    def undo(self) -> bool:
        """撤销上一步；返回是否真正执行了撤销。"""
        if self._restoring:
            return False
        self._discard_session()
        self._flush_merge()          # 未切换参数的“连续修改”也视为已完成的一步
        if not self.undo_stack:
            self._notify_changed()
            return False
        before = self.undo_stack.pop()
        self.redo_stack.append(self._capture())
        self._restore_internal(before)
        self._notify_changed()
        return True

    def redo(self) -> bool:
        """重做下一步；返回是否真正执行了重做。"""
        if self._restoring:
            return False
        self._discard_session()
        self._flush_merge()          # 与撤销一致：先把待合并的设置步骤提交为一步
        if not self.redo_stack:
            self._notify_changed()
            return False
        after = self.redo_stack.pop()
        # 当前状态即该步的“操作前”状态：放回撤销栈，使“重做后仍可撤销”成立
        # （撤销栈只保存“操作前”快照，不能把“操作后”快照 after 直接放回）
        self.undo_stack.append(self._capture())
        self._restore_internal(after)
        self._notify_changed()
        return True

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    # ────────────── 内部 ──────────────
    def _restore_internal(self, snap):
        self._restoring = True
        try:
            self._restore(snap)
        finally:
            self._restoring = False

    def _discard_session(self):
        self._session = None

    def _flush_merge(self):
        """提交待合并的设置步骤（不清除重做栈，供撤销路径复用）。"""
        if self._merge_key is not None:
            self._push_no_clear(self._merge_snapshot)
            self._merge_key = None
            self._merge_snapshot = None

    def _push_no_clear(self, snap):
        if snap is None:
            return
        self.undo_stack.append(snap)
        if len(self.undo_stack) > self._max_steps:
            del self.undo_stack[0]

    def _push(self, snap):
        self._push_no_clear(snap)
        self.redo_stack.clear()      # 产生新操作后，重做栈失效
        self._notify_changed()

    def _notify_changed(self):
        if self._on_changed is not None:
            try:
                self._on_changed()
            except Exception:
                pass


def deepcopy_snapshot(payload: dict) -> dict:
    """深拷贝快照载荷，避免快照与实时数据共享可变对象。"""
    return copy.deepcopy(payload)
