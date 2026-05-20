"""
方案图数据层
"""

class SchemeSceneData:
    """保存每张方案图的点位数据、分组信息、节点编辑状态等核心数据，并提供相关操作方法。"""
    def setup_scene_data(self):
        """初始化数据层状态。"""
        self.node_points = {0: []}  # 下标为时间轴节点索引保存点位列表，每个点位包含 (id、x、y、group_id) 等信息
        self.node_textboxes = {0: []}  # 下标为时间轴节点索引保存文本框列表
        self.node_manual_edited = {0: False}    # 按时间轴节点索引保存是否手动编辑过的状态，自动插值时以此判断是否覆盖
        
        # node 为下标，存储[set(group_ids), ...]，
        self.node_to_group = [set()]  # 点位分组信息，每个分组包含 node（分组所属的节点）、point_ids（组内点位 ID 列表）、leader_id（leader 点位 ID） 等信息
        
        # group_id 为下标，存储[dict([point_ids], leader_pos), ...]，用于快速查询分组内点位 ID 列表。
        # leader 为 bool 值，表示选择首/尾的点位作为组内 leader。
        self.group_to_point = []   # 分组信息列表，每个元素包含 [point_ids]
        
        self.active_node = 0    # 当前选中的时间轴节点索引，默认为0
        self.active_tool = "框选"   # 当前选中的工具，默认为框选
        self.preview_beat = 0   # 当前预览的拍位，用于非节点拍位的插值显示，默认为0

        self._next_point_id = 1 # 点位ID自增计数器，确保每个新点位都有唯一ID
        self._next_textbox_id = 1 # 文本框ID自增计数器
        # self._next_group_id = 1 # 分组ID自增计数器，确保每个新分组都有唯一ID
        self._pending_points = []   # 当前工具操作中尚未提交的数据点位列表，如绘制中的线段或多边形顶点等

    def ensure_node_exists(self, node_index: int):
        """确保目标节点存在；新节点默认复制前一节点点位。"""
        idx = max(0, int(node_index))
        if idx in self.node_points:
            return

        if idx == 0:
            self.node_points[0] = []
            self.node_textboxes[0] = []
            self.node_manual_edited[0] = self.node_manual_edited.get(0, False)
            return

        prev_points = self.node_points.get(idx - 1, [])
        self.node_points[idx] = [
            {"id": p["id"], "x": p["x"], "y": p["y"], "group_id": p.get("group_id")}
            for p in prev_points
        ]
        self.node_textboxes[idx] = []
        self.node_manual_edited[idx] = False

    def on_node_added(self, node_index: int):
        """在时间轴末尾添加新节点后，确保节点数据结构完整并切换到新节点。"""
        self.ensure_node_exists(node_index)
        self.node_to_group.append(self.node_to_group[-1])
        self._render_points_for_active_node()

    def on_node_inserted(self, node_index: int):
        """在中间拍位插入节点后，按新时间轴索引重排并初始化新节点点位。"""
        inserted_index = int(node_index)

        # 重排节点索引：从后往前遍历，遇到索引 >= inserted_index 的节点都往后挪一位。
        moved_points = {}
        for idx in sorted(self.node_points.keys(), reverse=True):
            if idx >= inserted_index:
                moved_points[idx + 1] = self.node_points[idx]
            else:
                moved_points[idx] = self.node_points[idx]
        self.node_points = moved_points

        moved_textboxes = {}
        for idx in sorted(self.node_textboxes.keys(), reverse=True):
            if idx >= inserted_index:
                moved_textboxes[idx + 1] = self.node_textboxes[idx]
            else:
                moved_textboxes[idx] = self.node_textboxes[idx]
        self.node_textboxes = moved_textboxes

        # 重排节点手动编辑状态
        moved_manual = {}
        for idx in sorted(self.node_manual_edited.keys(), reverse=True):
            if idx >= inserted_index:
                moved_manual[idx + 1] = self.node_manual_edited[idx]
            else:
                moved_manual[idx] = self.node_manual_edited[idx]
        self.node_manual_edited = moved_manual
        
        # 添加新节点的分组信息
        self.node_to_group.insert(inserted_index, self.node_to_group[inserted_index - 1] if inserted_index - 1 >= 0 else set())
        
        # 新节点点位初始化
        left_idx = inserted_index - 1
        right_idx = inserted_index + 1
        if left_idx in self.node_points and right_idx in self.node_points:  # 如果左右节点都存在则插值
            self.node_points[inserted_index] = self._interpolate_points_between_nodes(left_idx, right_idx, inserted_index)
        else:   # 复制左节点（如果存在）
            self.node_points[inserted_index] = self._copy_points(left_idx)

        self.node_textboxes[inserted_index] = []

        # self.node_shapes[inserted_index] = []
        self.node_manual_edited[inserted_index] = False # 手动编辑状态默认为 False。

        self._render_points_for_active_node()

    def on_node_deleted(self, node_index: int):
        """删除节点后，按时间轴索引重排并清理相关数据。"""
        removed_index = int(node_index)
        if removed_index <= 0:
            return

        # 重排节点索引
        new_points = {}
        for idx in sorted(self.node_points.keys()):
            if idx < removed_index:
                new_points[idx] = self.node_points[idx]
            elif idx > removed_index:
                new_points[idx - 1] = self.node_points[idx]
        if 0 not in new_points:
            new_points[0] = []
        self.node_points = new_points

        new_textboxes = {}
        for idx in sorted(self.node_textboxes.keys()):
            if idx < removed_index:
                new_textboxes[idx] = self.node_textboxes[idx]
            elif idx > removed_index:
                new_textboxes[idx - 1] = self.node_textboxes[idx]
        if 0 not in new_textboxes:
            new_textboxes[0] = []
        self.node_textboxes = new_textboxes

        # 修改分组信息（如果被删除节点的分组信息与后续节点有重叠，则保留后续节点的分组信息，否则删除）
        # del_group = self.node_to_group[removed_index]
        # for group in self.node_to_group[removed_index + 1:]:
        #     del_group = del_group - group
        #     if del_group is None:
        #         break
        self.node_to_group.pop(removed_index)
        # if del_group:
        #     self.group_to_point = [group for group in self.group_to_point if group[0] not in del_group]

        # 重排节点手动编辑状态
        new_manual = {}
        for idx in sorted(self.node_manual_edited.keys()):
            if idx < removed_index:
                new_manual[idx] = self.node_manual_edited[idx]
            elif idx > removed_index:
                new_manual[idx - 1] = self.node_manual_edited[idx]
        if 0 not in new_manual:
            new_manual[0] = False
        self.node_manual_edited = new_manual

        # 调整当前选中节点索引
        if self.active_node >= removed_index:
            self.active_node = max(0, self.active_node - 1)
        self._pending_points = []
        self._clear_draft()
        self._render_points_for_active_node()

    # def export_node_points(self) -> dict:
    #     """导出按图绑定的点位数据（用于后续保存方案文件）。"""
    #     return {
    #         idx: [
    #             {"id": p["id"], "x": p["x"], "y": p["y"], "group_id": p.get("group_id")}
    #             for p in points
    #         ]
    #         for idx, points in sorted(self.node_points.items())
    #     }

    # def export_point_groups(self) -> list[dict]:
    #     return [
    #         {
    #             "id": group["id"],
    #             "node": group["node"],
    #             "tool": group["tool"],
    #             "point_ids": list(group["point_ids"]),
    #             "leader_id": group.get("leader_id"),
    #         }
    #         for group in self.point_groups
    #     ]

    # def export_node_shapes(self) -> dict:
    #     return {
    #         idx: [dict(shape) for shape in shapes]
    #         for idx, shapes in sorted(self.node_shapes.items())
    #     }

    def _mark_node_manual(self, node_index: int):
        """标记节点为手动编辑过，用于后续自动插值时判断是否覆盖。"""
        self.node_manual_edited[max(0, int(node_index))] = True

    def _node_start_beat(self, node_index: int) -> int:
        """返回节点起始拍位，默认为节点索引对应的整数拍。"""
        parent = self.parent()
        timeline = getattr(parent, "timelineMainWidget", None)
        # if timeline is not None and hasattr(timeline, "start_beat_of"):
        if timeline is not None:
            try:
                return int(timeline.start_beat_of(int(node_index)))
            except Exception:
                pass
        return int(node_index)

    def _points_for_node_render(self, node_index: int) -> list[dict]:
        """获取用于渲染的节点点位；调整会话中当前节点优先返回预览点位。"""
        adjustment_active = bool(getattr(self, "_adjustment_active", False))
        adjustment_preview_points = getattr(self, "_adjustment_preview_points", [])
        active_node = int(getattr(self, "active_node", -1))
        if adjustment_active and int(node_index) == active_node and adjustment_preview_points:
            return adjustment_preview_points
        return self.node_points.get(int(node_index), [])

    def _interpolate_points_between_nodes(self, start_node: int, end_node: int, target_node: int) -> list[dict]:
        """按节点起始拍对齐，计算 target_node 的插值点位。"""
        # start_points = self.node_points.get(start_node, [])
        # end_points = self.node_points.get(end_node, [])
        start_points = self._points_for_node_render(start_node)
        end_points = self._points_for_node_render(end_node)
        start_map = {int(p["id"]): p for p in start_points}
        end_map = {int(p["id"]): p for p in end_points}

        start_beat = self._node_start_beat(start_node)
        end_beat = self._node_start_beat(end_node)
        target_beat = self._node_start_beat(target_node)
        denom = end_beat - start_beat
        if abs(denom) <= 1e-9:
            t = 0.0
        else:
            t = max(0.0, min(1.0, (target_beat - start_beat) / denom))

        points = []
        for point_id in sorted(set(start_map.keys()) | set(end_map.keys())):
            sp = start_map.get(point_id)
            ep = end_map.get(point_id)
            if sp is not None and ep is not None:
                point = {
                    "id": point_id,
                    "x": float(sp["x"]) + (float(ep["x"]) - float(sp["x"])) * t,
                    "y": float(sp["y"]) + (float(ep["y"]) - float(sp["y"])) * t,
                }
                group_id = ep.get("group_id", sp.get("group_id"))
                if group_id is not None:
                    point["group_id"] = group_id
                points.append(point)
            elif sp is not None:
                point = {"id": point_id, "x": float(sp["x"]), "y": float(sp["y"])}
                if sp.get("group_id") is not None:
                    point["group_id"] = sp.get("group_id")
                points.append(point)
            elif ep is not None:
                point = {"id": point_id, "x": float(ep["x"]), "y": float(ep["y"])}
                if ep.get("group_id") is not None:
                    point["group_id"] = ep.get("group_id")
                points.append(point)
        return points

    def _interpolate_points_at_beat(self, start_node: int, end_node: int, target_beat: int) -> list[dict]:
        """按任意拍位进行插值，用于非节点拍位预览。"""
        # start_points = self.node_points.get(start_node, [])
        # end_points = self.node_points.get(end_node, [])
        start_points = self._points_for_node_render(start_node)
        end_points = self._points_for_node_render(end_node)
        
        start_map = {int(p["id"]): p for p in start_points}
        end_map = {int(p["id"]): p for p in end_points}

        start_beat = self._node_start_beat(start_node)
        end_beat = self._node_start_beat(end_node)
        denom = end_beat - start_beat
        if abs(denom) <= 1e-9:
            t = 0.0
        else:
            t = max(0.0, min(1.0, (int(target_beat) - start_beat) / denom))

        points = []
        for point_id in sorted(set(start_map.keys()) | set(end_map.keys())):
            sp = start_map.get(point_id)
            ep = end_map.get(point_id)
            if sp is not None and ep is not None:
                point = {
                    "id": point_id,
                    "x": float(sp["x"]) + (float(ep["x"]) - float(sp["x"])) * t,
                    "y": float(sp["y"]) + (float(ep["y"]) - float(sp["y"])) * t,
                }
                group_id = ep.get("group_id", sp.get("group_id"))
                if group_id is not None:
                    point["group_id"] = group_id
                points.append(point)
            elif sp is not None:
                point = {"id": point_id, "x": float(sp["x"]), "y": float(sp["y"])}
                if sp.get("group_id") is not None:
                    point["group_id"] = sp.get("group_id")
                points.append(point)
            elif ep is not None:
                point = {"id": point_id, "x": float(ep["x"]), "y": float(ep["y"])}
                if ep.get("group_id") is not None:
                    point["group_id"] = ep.get("group_id")
                points.append(point)
        return points

    def _node_index_at_beat(self, beat: int) -> int | None:
        """若 beat 与某节点起始拍重合，返回节点索引。"""
        target = int(beat)
        max_node = max(self.node_points.keys(), default=0)
        for idx in range(0, max_node + 1):
            if self._node_start_beat(idx) == target:
                return idx
        return None

    def _segment_for_beat(self, beat: int) -> tuple[int, int] | None:
        """返回 beat 所在区间 [left_node, right_node]。"""
        target = int(beat)
        max_node = max(self.node_points.keys(), default=0)
        if max_node <= 0:
            return None

        starts = [self._node_start_beat(i) for i in range(max_node + 1)]
        for left in range(0, max_node):
            if starts[left] < target < starts[left + 1]:
                return left, left + 1
        return None

    def set_preview_beat(self, beat: int, *args):
        """设置当前预览拍位，并刷新显示。"""
        self.preview_beat = max(0, int(beat))
        self._render_points_for_active_node()

    def _is_current_beat_editable(self) -> bool:
        """只有拍位落在当前选中节点起始拍时允许编辑。"""
        node_at_beat = self._node_index_at_beat(self.preview_beat)
        return node_at_beat is not None and node_at_beat == self.active_node

    def _copy_points(self, source_node: int) -> list[dict]:
        """复制 source_node 的点位数据，用于新节点初始化。"""
        copied = []
        for p in self.node_points.get(source_node, []):
            point = {"id": p["id"], "x": p["x"], "y": p["y"]}
            if p.get("group_id") is not None:
                point["group_id"] = p.get("group_id")
            copied.append(point)
        return copied

    def _recalculate_following_auto_nodes(self, changed_node: int, include_manual_nodes: bool = False):
        """在 changed_node 发生修改后，自动调整后续节点的点位；如果 include_manual_nodes 为 True 则连同手动编辑过的节点一起调整。"""
        max_node = max(self.node_points.keys(), default=0)
        changed_node = int(changed_node)
        if changed_node >= max_node:
            return

        segment_start = changed_node
        while segment_start < max_node:
            next_manual = None
            for idx in range(segment_start + 1, max_node + 1):
                if self.node_manual_edited.get(idx, False):
                    next_manual = idx
                    break

            if next_manual is None:
                for idx in range(segment_start + 1, max_node + 1):
                    if include_manual_nodes or not self.node_manual_edited.get(idx, False):
                        self.node_points[idx] = self._copy_points(segment_start)
                break

            for idx in range(segment_start + 1, next_manual):
                if include_manual_nodes or not self.node_manual_edited.get(idx, False):
                    self.node_points[idx] = self._interpolate_points_between_nodes(segment_start, next_manual, idx)

            if include_manual_nodes and self.node_manual_edited.get(next_manual, False):
                self.node_points[next_manual] = self._interpolate_points_between_nodes(segment_start, next_manual, next_manual)

            segment_start = next_manual