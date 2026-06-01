"""
方案图数据层
"""

class SchemeSceneData:
    """保存每张方案图的点位数据、分组信息、节点编辑状态等核心数据，并提供相关操作方法。"""
    def setup_scene_data(self):
        """初始化数据层状态。"""
        self.node_points = [[]]  # 下标为时间轴节点索引, 保存点位列表，每个点位包含 (id、x、y、group_id) 等信息
        self.node_textboxes = {}  # 下标为时间轴节点索引, 保存文本框列表
        self.node_manual_edited = [False]    # 按时间轴节点索引保存是否手动编辑过的状态，自动插值时以此判断是否覆盖
        
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
        
        # node_paths: 每个节点下按参考点ID保存路径定义，路径定义包含 path（路径点列表）和 members（成员点位与路径偏移量的映射）。
        # 格式: { node_index: # 节点索引
        # [{"path": [(x,y), ...], # 路径点列表
        # "anchor_id": int, # 锚点ID，用于计算路径偏移量的参考点
        # "members": [point_ids] # 成员点位ID列表
        # }], ...] }
        self.node_paths = {}

    def _find_point_in_node(self, node_index: int, point_id: int):
        """在指定节点中按点位ID查找点位字典。"""
        for point in self.node_points[node_index]:
            if int(point.get("id", -1)) == int(point_id):
                return point
        return None

    def _normalize_node_path_entry(self, ref_entry: dict) -> dict | None:
        """把 node_paths 记录整理成内部使用的列表结构。"""
        if not isinstance(ref_entry, dict):
            return None

        anchor_id = ref_entry.get("anchor_id")

        path_raw = ref_entry.get("path", [])
        path = []
        if isinstance(path_raw, list):
            for item in path_raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        path.append((float(item[0]), float(item[1])))
                    except Exception:
                        continue

        members_raw = ref_entry.get("members", [])
        members = []
        if isinstance(members_raw, (list, tuple, set)):
            for pid in members_raw:
                try:
                    members.append(int(pid))
                except Exception:
                    continue

        seen = set()
        members = [pid for pid in members if not (pid in seen or seen.add(pid))]

        return {"anchor_id": anchor_id, "path": path, "members": members}

    def _upsert_node_path_entry(self, node_index: int, anchor_id: int, path: list[tuple[float, float]], members: list[int]):
        """在指定节点中新增或更新一条路径定义。"""
        idx = max(0, int(node_index))
        entry = {
            "anchor_id": int(anchor_id),
            "path": [(float(x), float(y)) for x, y in path],
            "members": [int(point_id) for point_id in members],
        }

        node_paths = self.node_paths.setdefault(idx, [])
        for entry_index, existed in enumerate(node_paths):
            if int(existed.get("anchor_id", -1)) == int(anchor_id):
                node_paths[entry_index] = entry
                break
        else:
            node_paths.append(entry)

    def _node_path_member_offset(self, node_index: int, ref_entry: dict, point_id: int) -> tuple[float, float]:
        """按当前节点里的锚点和成员点位现算偏移。"""
        anchor_id = ref_entry.get("anchor_id")
        if anchor_id is None:
            return 0.0, 0.0
        anchor_point = self._find_point_in_node(node_index, int(anchor_id))
        member_point = self._find_point_in_node(node_index, int(point_id))
        if anchor_point is None or member_point is None:
            return 0.0, 0.0
        return (
            float(member_point.get("x", 0.0)) - float(anchor_point.get("x", 0.0)),
            float(member_point.get("y", 0.0)) - float(anchor_point.get("y", 0.0)),
        )

    def export_confirmed_state(self) -> dict:
        """导出已确认的方案图数据，用于保存到方案文件。"""
        return {
            "node_points": self.node_points,
            # {
            #     str(idx): [dict(point) for point in points]
            #     for idx, points in sorted(self.node_points.items())
            # },
            "node_textboxes": {
                str(idx): [dict(textbox) for textbox in textboxes]
                for idx, textboxes in sorted(self.node_textboxes.items())
            },
            "node_manual_edited": [bool(flag) for flag in self.node_manual_edited],
            "node_to_group": [sorted(int(group_id) for group_id in group_ids) for group_ids in self.node_to_group],
            "group_to_point": [
                {
                    **dict(group),
                    "point_ids": [int(point_id) for point_id in group.get("point_ids", [])],
                }
                for group in self.group_to_point
            ],
            "node_paths": {
                str(node): [
                    {
                        "anchor_id": int(ref_entry.get("anchor_id", -1)),
                        "path": [[float(x), float(y)] for x, y in ref_entry.get("path", [])],
                        "members": [int(point_id) for point_id in ref_entry.get("members", [])],
                    }
                    for ref_entry in refs
                    if isinstance(ref_entry, dict)
                ]
                for node, refs in sorted(self.node_paths.items())
                if refs
            },
            "_next_point_id": int(self._next_point_id),
            "_next_textbox_id": int(self._next_textbox_id),
        }

    def load_confirmed_state(self, data: dict, node_count: int | None = None):
        """从保存文件恢复已确认的方案图数据。"""
        if not isinstance(data, dict):
            raise ValueError("方案文件中的场景数据格式无效")

        self.setup_scene_data()

        self.node_points = data.get("node_points", [[]])
        # if not isinstance(node_points_data, dict):
        #     raise ValueError("方案文件中的 node_points 格式无效")
        # self.node_points = {}
        # for node_index, points in enumerate(node_points_data):
        #     # node_index = max(0, int(node_key))
        #     if not isinstance(points, list):
        #         raise ValueError(f"方案文件中的 node_points[{node_key}] 格式无效")
        #     self.node_points
        #     self.node_points[node_index] = [dict(point) for point in points if isinstance(point, dict)]
        # self.node_points.setdefault(0, [])

        node_textboxes_data = data.get("node_textboxes", {})
        if not isinstance(node_textboxes_data, dict):
            raise ValueError("方案文件中的 node_textboxes 格式无效")
        self.node_textboxes = {}
        for node_key, textboxes in node_textboxes_data.items():
            node_index = max(0, int(node_key))
            if not isinstance(textboxes, list):
                raise ValueError(f"方案文件中的 node_textboxes[{node_key}] 格式无效")
            self.node_textboxes[node_index] = [dict(textbox) for textbox in textboxes if isinstance(textbox, dict)]
        self.node_textboxes.setdefault(0, [])

        node_manual_data = data.get("node_manual_edited", [])
        if not isinstance(node_manual_data, list):
            raise ValueError("方案文件中的 node_manual_edited 格式无效")
        self.node_manual_edited = [bool(flag) for flag in node_manual_data]
        if not self.node_manual_edited:
            self.node_manual_edited = [False]

        node_to_group_data = data.get("node_to_group", [])
        if not isinstance(node_to_group_data, list):
            raise ValueError("方案文件中的 node_to_group 格式无效")
        self.node_to_group = []
        for group_ids in node_to_group_data:
            if isinstance(group_ids, (list, tuple, set)):
                self.node_to_group.append({int(group_id) for group_id in group_ids})
            else:
                self.node_to_group.append(set())
        if not self.node_to_group:
            self.node_to_group = [set()]

        # load node_paths
        node_paths_data = data.get("node_paths", {})
        self.node_paths = {}
        if isinstance(node_paths_data, dict):
            for node_key, refs in node_paths_data.items():
                try:
                    node_index = max(0, int(node_key))
                except Exception:
                    continue

                entries = []
                if not isinstance(refs, list):
                    continue
                for ref_entry in refs:
                    normalized = self._normalize_node_path_entry(ref_entry)
                    if normalized is not None:
                        entries.append(normalized)
                if entries:
                    self.node_paths[node_index] = entries

        group_to_point_data = data.get("group_to_point", [])
        if not isinstance(group_to_point_data, list):
            raise ValueError("方案文件中的 group_to_point 格式无效")
        self.group_to_point = []
        for group in group_to_point_data:
            if not isinstance(group, dict):
                continue
            group_data = dict(group)
            group_data["point_ids"] = [int(point_id) for point_id in group_data.get("point_ids", [])]
            self.group_to_point.append(group_data)

        max_point_id = 0
        for points in self.node_points:
            for point in points:
                try:
                    max_point_id = max(max_point_id, int(point.get("id", 0)))
                except Exception:
                    continue
        for group in self.group_to_point:
            for point_id in group.get("point_ids", []):
                try:
                    max_point_id = max(max_point_id, int(point_id))
                except Exception:
                    continue

        max_textbox_id = 0
        for textboxes in self.node_textboxes.values():
            for textbox in textboxes:
                try:
                    max_textbox_id = max(max_textbox_id, int(textbox.get("id", 0)))
                except Exception:
                    continue

        saved_next_point_id = int(data.get("_next_point_id", max_point_id + 1))
        saved_next_textbox_id = int(data.get("_next_textbox_id", max_textbox_id + 1))
        self._next_point_id = max(1, max_point_id + 1, saved_next_point_id)
        self._next_textbox_id = max(1, max_textbox_id + 1, saved_next_textbox_id)

        # 确保基础节点结构完整，避免后续渲染时访问缺失索引。
        expected_node_count = max(1, int(node_count)) if node_count is not None else 0
        max_node_index = max(
            len(self.node_points),
            max(self.node_textboxes.keys(), default=0),
            len(self.node_manual_edited) - 1,
            len(self.node_to_group) - 1,
            max(self.node_paths.keys(), default=0),
            expected_node_count - 1,
        )
        for idx in range(0, max_node_index + 1):
            self.node_points.append([]) if idx >= len(self.node_points) else None
            self.node_textboxes.setdefault(idx, [])
            self.node_paths.setdefault(idx, [])
        while len(self.node_to_group) <= max_node_index:
            self.node_to_group.append(set())

    def ensure_node_exists(self, node_index: int):
        """确保目标节点存在；新节点默认复制前一节点点位。"""
        idx = max(0, int(node_index))
        if idx < len(self.node_points):
            return

        if idx == 0:
            self.node_points[0] = []
            return

        # self.node_points.append([])
        self.node_manual_edited.append(False)
        
        prev_points = self.node_points[idx - 1] if idx - 1 < len(self.node_points) else []
        self.node_points.append([
            {"id": p["id"], "x": p["x"], "y": p["y"], "group_id": p.get("group_id")}
            for p in prev_points
        ])
        self.node_paths.setdefault(idx, [])

    def on_node_added(self, node_index: int):
        """在时间轴末尾添加新节点后，确保节点数据结构完整并切换到新节点。"""
        self.ensure_node_exists(node_index)
        self.node_to_group.append(self.node_to_group[-1])
        self._render_points_for_active_node()

    def _split_node_path_entry_at_midpoint(self, path_info: dict) -> tuple[dict, dict]:
        """把单条路径定义按路径长度中点拆成左右两段。"""
        if path_info is None:
            empty_entry = {"anchor_id": None, "path": [], "members": []}
            return empty_entry, empty_entry.copy()

        path = path_info['path']
        if len(path) < 2:
            left_path = list(path)
            right_path = list(path)
        else:
            import math

            segment_lengths = []
            cumulative_lengths = [0.0]
            total_length = 0.0
            for idx in range(len(path) - 1):
                ax, ay = path[idx]
                bx, by = path[idx + 1]
                segment_length = math.hypot(bx - ax, by - ay)
                segment_lengths.append(segment_length)
                total_length += segment_length
                cumulative_lengths.append(total_length)

            if total_length <= 1e-9:
                mid_idx = len(path) // 2
                left_path = path[: mid_idx + 1]
                right_path = path[mid_idx:]
            else:
                mid_length = total_length / 2.0
                closest_idx = min(range(len(cumulative_lengths)), key=lambda idx: abs(cumulative_lengths[idx] - mid_length))
                if abs(cumulative_lengths[closest_idx] - mid_length) <= 1e-6:
                    split_idx = closest_idx
                    left_path = path[: split_idx + 1]
                    right_path = path[split_idx:]
                else:
                    split_point = None
                    split_idx = 0
                    running = 0.0
                    for idx, segment_length in enumerate(segment_lengths):
                        next_running = running + segment_length
                        if next_running >= mid_length:
                            split_idx = idx
                            if segment_length <= 1e-9:
                                split_point = (float(path[idx][0]), float(path[idx][1]))
                            else:
                                local_progress = (mid_length - running) / segment_length
                                ax, ay = path[idx]
                                bx, by = path[idx + 1]
                                split_point = (
                                    float(ax) + (float(bx) - float(ax)) * local_progress,
                                    float(ay) + (float(by) - float(ay)) * local_progress,
                                )
                            break
                        running = next_running

                    if split_point is None:
                        split_point = (float(path[-1][0]), float(path[-1][1]))
                        split_idx = len(path) - 1

                    left_path = path[: split_idx + 1] + [split_point]
                    right_path = [split_point] + path[split_idx + 1 :]

        if not path:
            left_path = []
            right_path = []

        left_entry = {
            "anchor_id": path_info.get("anchor_id"),
            "path": left_path,
            "members": list(path_info.get("members", [])),
        }
        right_entry = {
            "anchor_id": path_info.get("anchor_id"),
            "path": right_path,
            "members": list(path_info.get("members", [])),
        }
        return left_entry, right_entry

    def on_node_inserted(self, node_index: int):
        """在中间拍位插入节点后，按新时间轴索引重排并初始化新节点点位。"""
        inserted_index = int(node_index)

        # 重排节点索引：从后往前遍历，遇到索引 >= inserted_index 的节点都往后挪一位。
        # self.node_points.insert(inserted_index, self.node_points[inserted_index - 1] if inserted_index - 1 >= 0 else [])
        # moved_points = {}
        # for idx in reversed(range(len(self.node_points))):
        #     if idx >= inserted_index:
        #         moved_points[idx + 1] = self.node_points[idx]
        #     else:
        #         moved_points[idx] = self.node_points[idx]
        # self.node_points = moved_points

        moved_textboxes = {}
        for idx in sorted(self.node_textboxes.keys(), reverse=True):
            if idx >= inserted_index:
                moved_textboxes[idx + 1] = self.node_textboxes[idx]
            else:
                moved_textboxes[idx] = self.node_textboxes[idx]
        self.node_textboxes = moved_textboxes


        # 重排节点手动编辑状态
        self.node_manual_edited.insert(inserted_index, False)
        
        # 添加新节点的分组信息
        self.node_to_group.insert(inserted_index, self.node_to_group[inserted_index - 1] if inserted_index - 1 >= 0 else set())
        
        # 新节点点位初始化
        left_idx = inserted_index - 1
        right_idx = inserted_index + 1
        self.node_paths[right_idx] = self.node_paths[inserted_index]
        
        if left_idx < len(self.node_points) and right_idx <= len(self.node_points):  # 如果左右节点都存在则插值
            # 插值新节点点位
            self.node_points.insert(inserted_index, [])
            self.node_points[inserted_index] = self._interpolate_points_at_beat(left_idx, right_idx, self._node_start_beat(inserted_index))
            
            # 更新路径设置
            # moved_paths = {}
            # for idx in sorted(self.node_paths.keys(), reverse=True):
            #     if idx >= inserted_index:
            #         moved_paths[idx + 1] = self.node_paths[idx]
            #     else:
            #         moved_paths[idx] = self.node_paths[idx]
            # right_paths = list(moved_paths.get(right_idx, []))
            left_paths = []
            split_right_paths = []
            for path_info in self.node_paths[right_idx]:
                left_entry, right_entry = self._split_node_path_entry_at_midpoint(path_info)
                left_paths.append(left_entry)
                split_right_paths.append(right_entry)
            self.node_paths[inserted_index] = left_paths
            self.node_paths[right_idx] = split_right_paths
            # moved_paths[right_idx] = split_right_paths
            # self.node_paths = moved_paths
        else:   # 复制左节点（如果存在）
            self.node_points.insert(inserted_index, self._copy_points(left_idx))

        # self.node_shapes[inserted_index] = []
        self.node_manual_edited[inserted_index] = False # 手动编辑状态默认为 False。

        self._render_points_for_active_node()

    def on_node_deleted(self, node_index: int):
        """删除节点后，按时间轴索引重排并清理相关数据。"""
        removed_index = int(node_index)
        if removed_index <= 0:
            return

        # 重排节点索引
        # new_points = {}
        # for idx in range(len(self.node_points)):
        #     if idx < removed_index:
        #         new_points[idx] = self.node_points[idx]
        #     elif idx > removed_index:
        #         new_points[idx - 1] = self.node_points[idx]
        # if 0 not in new_points:
        #     new_points[0] = []
        # self.node_points = new_points
        self.node_points.pop(removed_index)

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

        # 直接舍弃被删除节点的路径数据
        new_paths = {}
        for idx in sorted(self.node_paths.keys()):
            # 重置索引
            if idx < removed_index:
                new_paths[idx] = self.node_paths[idx]
            elif idx > removed_index + 1:
                new_paths[idx - 1] = self.node_paths[idx]
        # for path_info, new_path_info in zip(self.node_paths[removed_index], new_paths[removed_index]):
        #     # 修复路径
        #     src_pos = path_info['path'][0]
        #     new_path_info['path'].insert(0, src_pos)
        self.node_paths = new_paths
        # if del_group:
        #     self.group_to_point = [group for group in self.group_to_point if group[0] not in del_group]

        # 重排节点手动编辑状态
        if removed_index < len(self.node_manual_edited):
            self.node_manual_edited.pop(removed_index)
        if not self.node_manual_edited:
            self.node_manual_edited = [False]

        # 调整当前选中节点索引
        if self.active_node >= removed_index:
            self.active_node = max(0, self.active_node - 1)
        # self._pending_points = []
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
        idx = max(0, int(node_index))
        self.node_manual_edited[idx] = True

    def _node_start_beat(self, node_index: int) -> int:
        """返回节点起始拍位，默认为节点索引对应的整数拍。"""
        parent = self.parent()
        timeline = getattr(parent, "timelineMainWidget", None)
        # if timeline is not None and hasattr(timeline, "start_beat_of"):
        if timeline is not None:
            return int(timeline.start_beat_of(int(node_index)))
        return int(node_index)

    def _points_for_node_render(self, node_index: int) -> list[dict]:
        """获取用于渲染的节点点位；调整会话中当前节点优先返回预览点位。"""
        adjustment_active = bool(getattr(self, "_adjustment_active", False))
        adjustment_preview_points = getattr(self, "_adjustment_preview_points", [])
        active_node = int(getattr(self, "active_node", -1))
        if adjustment_active and node_index == active_node and adjustment_preview_points:
            return adjustment_preview_points
        return self.node_points[node_index]

    def _sample_position_along_path(self, path: list[tuple[float, float]], progress: float) -> tuple[float, float] | None:
        """按路径累计长度采样位置。"""
        if not path:
            return None

        if len(path) == 1:
            return float(path[0][0]), float(path[0][1])

        import math

        segments = []
        total_length = 0.0
        for idx in range(len(path) - 1):
            ax, ay = path[idx]
            bx, by = path[idx + 1]
            segment_length = math.hypot(bx - ax, by - ay)
            segments.append((segment_length, (ax, ay), (bx, by)))
            total_length += segment_length

        if total_length <= 1e-9:
            return float(path[0][0]), float(path[0][1])

        target_length = max(0.0, min(1.0, float(progress))) * total_length
        accumulated = 0.0
        for segment_length, start_point, end_point in segments:
            if accumulated + segment_length >= target_length:
                if segment_length <= 1e-9:
                    return float(start_point[0]), float(start_point[1])
                local_progress = (target_length - accumulated) / segment_length
                x = start_point[0] + (end_point[0] - start_point[0]) * local_progress
                y = start_point[1] + (end_point[1] - start_point[1]) * local_progress
                return float(x), float(y)
            accumulated += segment_length

        return float(path[-1][0]), float(path[-1][1])

    def _sample_point_from_node_path(self, node_index: int, point_id: int, progress: float) -> tuple[float, float] | None:
        """若点位在节点路径中，按路径进度采样其位置。"""
        node_paths = self.node_paths.get(int(node_index), [])
        for ref_entry in node_paths:
            members = ref_entry.get("members", [])
            if int(point_id) not in {int(pid) for pid in members}:
                continue
            sampled = self._sample_position_along_path(ref_entry.get("path", []), progress)
            if sampled is None:
                return None
            offset = self._node_path_member_offset(node_index, ref_entry, int(point_id))
            return float(sampled[0]) + float(offset[0]), float(sampled[1]) + float(offset[1])
        return None

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
                sampled = self._sample_point_from_node_path(end_node, point_id, t)
                if sampled is not None:
                    px, py = sampled
                    point = {"id": point_id, "x": float(px), "y": float(py)}
                else:
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
                point = {"id": point_id, "x": float(sp["x"]), "y": float(sp["y"]) }
                if sp.get("group_id") is not None:
                    point["group_id"] = sp.get("group_id")
                points.append(point)
            elif ep is not None:
                sampled = self._sample_point_from_node_path(end_node, point_id, t)
                if sampled is not None:
                    px, py = sampled
                    point = {"id": point_id, "x": float(px), "y": float(py)}
                else:
                    point = {"id": point_id, "x": float(ep["x"]), "y": float(ep["y"]) }
                if ep.get("group_id") is not None:
                    point["group_id"] = ep.get("group_id")
                points.append(point)
        return points

    def _node_index_at_beat(self, beat: int) -> int | None:
        """若 beat 与某节点起始拍重合，返回节点索引。"""
        target = int(beat)
        max_node = len(self.node_points) - 1
        for idx in range(0, max_node + 1):
            if self._node_start_beat(idx) == target:
                return idx
        return None

    def _segment_for_beat(self, beat: int) -> tuple[int, int] | None:
        """返回 beat 所在区间 [left_node, right_node]。"""
        target = int(beat)
        max_node = len(self.node_points) - 1
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
        for p in self.node_points[source_node]:
            point = {"id": p["id"], "x": p["x"], "y": p["y"]}
            if p.get("group_id") is not None:
                point["group_id"] = p.get("group_id")
            copied.append(point)
        return copied

    def _recalculate_following_auto_nodes(self, changed_node: int, include_manual_nodes: bool = False):
        """在 changed_node 发生修改后，自动调整后续节点的点位；如果 include_manual_nodes 为 True 则连同手动编辑过的节点一起调整。"""
        max_node = len(self.node_points) - 1
        changed_node = int(changed_node)
        if changed_node >= max_node:
            return

        segment_start = changed_node
        while segment_start < max_node:
            next_manual = None
            for idx in range(segment_start + 1, max_node + 1):
                if self.node_manual_edited[idx]:
                    next_manual = idx
                    break

            if next_manual is None:
                for idx in range(segment_start + 1, max_node + 1):
                    if include_manual_nodes or not self.node_manual_edited[idx]:
                        self.node_points[idx] = self._copy_points(segment_start)
                break

            for idx in range(segment_start + 1, next_manual):
                if include_manual_nodes or not self.node_manual_edited[idx]:
                    self.node_points[idx] = self._interpolate_points_at_beat(segment_start, next_manual, self._node_start_beat(idx))

            if include_manual_nodes and self.node_manual_edited[next_manual]:
                self.node_points[next_manual] = self._interpolate_points_at_beat(segment_start, next_manual, self._node_start_beat(next_manual))

            segment_start = next_manual