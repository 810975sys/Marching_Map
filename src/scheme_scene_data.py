class SchemeSceneDataMixin:
    """SchemeScene 的数据层：节点状态、插值和导出逻辑。"""

    def setup_scene_data(self):
        """初始化数据层状态。"""
        self.node_points = {0: []}
        self.node_shapes = {0: []}
        self.node_manual_edited = {0: False}
        self.point_groups = []
        self.active_node = 0
        self.active_tool = "框选"
        self.preview_beat = 0

        self._next_point_id = 1
        self._next_group_id = 1
        self._pending_points = []
        self._selected_point_ids = set()

    def set_active_tool(self, tool_name: str):
        """切换当前工具并清空临时草稿。"""
        self.active_tool = tool_name
        self._pending_points = []
        if tool_name != "框选":
            self._selected_point_ids.clear()
            self._clear_selection_rect()
        self._clear_draft()
        self._render_points_for_active_node()

    def set_active_node(self, node_index: int):
        """切换当前时间轴节点并刷新显示。"""
        self.active_node = max(0, int(node_index))
        self.ensure_node_exists(self.active_node)
        self._pending_points = []
        self._selected_point_ids.clear()
        self._clear_selection_rect()
        self._clear_draft()
        self._render_points_for_active_node()

    def ensure_node_exists(self, node_index: int):
        """确保目标节点存在；新节点默认复制前一节点点位。"""
        idx = max(0, int(node_index))
        if idx in self.node_points:
            return

        if idx == 0:
            self.node_points[0] = []
            self.node_shapes[0] = []
            self.node_manual_edited[0] = self.node_manual_edited.get(0, False)
            return

        prev_points = self.node_points.get(idx - 1, [])
        self.node_points[idx] = [
            {"id": p["id"], "x": p["x"], "y": p["y"], "group_id": p.get("group_id")}
            for p in prev_points
        ]
        self.node_shapes[idx] = []
        self.node_manual_edited[idx] = False

    def on_node_added(self, node_index: int):
        self.ensure_node_exists(node_index)
        self._render_points_for_active_node()

    def on_node_inserted(self, node_index: int):
        """在中间拍位插入节点后，按新时间轴索引重排并初始化新节点点位。"""
        inserted_index = int(node_index)
        if inserted_index <= 0:
            return

        moved_points = {}
        for idx in sorted(self.node_points.keys(), reverse=True):
            if idx >= inserted_index:
                moved_points[idx + 1] = self.node_points[idx]
            else:
                moved_points[idx] = self.node_points[idx]
        self.node_points = moved_points

        moved_shapes = {}
        for idx in sorted(self.node_shapes.keys(), reverse=True):
            if idx >= inserted_index:
                moved_shapes[idx + 1] = self.node_shapes[idx]
            else:
                moved_shapes[idx] = self.node_shapes[idx]
        self.node_shapes = moved_shapes

        moved_manual = {}
        for idx in sorted(self.node_manual_edited.keys(), reverse=True):
            if idx >= inserted_index:
                moved_manual[idx + 1] = self.node_manual_edited[idx]
            else:
                moved_manual[idx] = self.node_manual_edited[idx]
        self.node_manual_edited = moved_manual

        for group in self.point_groups:
            if int(group.get("node", 0)) >= inserted_index:
                group["node"] = int(group.get("node", 0)) + 1

        left_idx = inserted_index - 1
        right_idx = inserted_index + 1
        if left_idx in self.node_points and right_idx in self.node_points:
            self.node_points[inserted_index] = self._interpolate_points_between_nodes(left_idx, right_idx, inserted_index)
        else:
            self.node_points[inserted_index] = self._copy_points(left_idx)

        self.node_shapes[inserted_index] = []
        self.node_manual_edited[inserted_index] = False

        self._render_points_for_active_node()

    def on_node_deleted(self, node_index: int):
        removed_index = int(node_index)
        if removed_index <= 0:
            return

        new_points = {}
        for idx in sorted(self.node_points.keys()):
            if idx < removed_index:
                new_points[idx] = self.node_points[idx]
            elif idx > removed_index:
                new_points[idx - 1] = self.node_points[idx]
        if 0 not in new_points:
            new_points[0] = []
        self.node_points = new_points

        new_shapes = {}
        for idx in sorted(self.node_shapes.keys()):
            if idx < removed_index:
                new_shapes[idx] = self.node_shapes[idx]
            elif idx > removed_index:
                new_shapes[idx - 1] = self.node_shapes[idx]
        if 0 not in new_shapes:
            new_shapes[0] = []
        self.node_shapes = new_shapes

        new_manual = {}
        for idx in sorted(self.node_manual_edited.keys()):
            if idx < removed_index:
                new_manual[idx] = self.node_manual_edited[idx]
            elif idx > removed_index:
                new_manual[idx - 1] = self.node_manual_edited[idx]
        if 0 not in new_manual:
            new_manual[0] = False
        self.node_manual_edited = new_manual

        new_groups = []
        for group in self.point_groups:
            group_copy = dict(group)
            if group_copy.get("node", 0) < removed_index:
                new_groups.append(group_copy)
            elif group_copy.get("node", 0) > removed_index:
                group_copy["node"] = group_copy.get("node", 0) - 1
                new_groups.append(group_copy)
        self.point_groups = new_groups

        if self.active_node >= removed_index:
            self.active_node = max(0, self.active_node - 1)
        self._pending_points = []
        self._clear_draft()
        self._render_points_for_active_node()

    def export_node_points(self) -> dict:
        """导出按图绑定的点位数据（用于后续保存方案文件）。"""
        return {
            idx: [
                {"id": p["id"], "x": p["x"], "y": p["y"], "group_id": p.get("group_id")}
                for p in points
            ]
            for idx, points in sorted(self.node_points.items())
        }

    def export_point_groups(self) -> list[dict]:
        return [
            {
                "id": group["id"],
                "node": group["node"],
                "tool": group["tool"],
                "point_ids": list(group["point_ids"]),
                "leader_id": group.get("leader_id"),
            }
            for group in self.point_groups
        ]

    def export_node_shapes(self) -> dict:
        return {
            idx: [dict(shape) for shape in shapes]
            for idx, shapes in sorted(self.node_shapes.items())
        }

    def _mark_node_manual(self, node_index: int):
        self.node_manual_edited[max(0, int(node_index))] = True

    def _node_start_beat(self, node_index: int) -> int:
        parent = self.parent()
        timeline = getattr(parent, "timelineMainWidget", None)
        if timeline is not None and hasattr(timeline, "start_beat_of"):
            try:
                return int(timeline.start_beat_of(int(node_index)))
            except Exception:
                pass
        return int(node_index)

    def _interpolate_points_between_nodes(self, start_node: int, end_node: int, target_node: int) -> list[dict]:
        """按节点起始拍对齐，计算 target_node 的插值点位。"""
        start_points = self.node_points.get(start_node, [])
        end_points = self.node_points.get(end_node, [])
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
        start_points = self.node_points.get(start_node, [])
        end_points = self.node_points.get(end_node, [])
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

    def set_preview_beat(self, beat: int):
        """设置当前预览拍位，并刷新显示。"""
        self.preview_beat = max(0, int(beat))
        self._render_points_for_active_node()

    def _is_current_beat_editable(self) -> bool:
        """只有拍位落在当前选中节点起始拍时允许编辑。"""
        node_at_beat = self._node_index_at_beat(self.preview_beat)
        return node_at_beat is not None and node_at_beat == self.active_node

    def _copy_points(self, source_node: int) -> list[dict]:
        copied = []
        for p in self.node_points.get(source_node, []):
            point = {"id": p["id"], "x": p["x"], "y": p["y"]}
            if p.get("group_id") is not None:
                point["group_id"] = p.get("group_id")
            copied.append(point)
        return copied

    def _recalculate_following_auto_nodes(self, changed_node: int, include_manual_nodes: bool = False):
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