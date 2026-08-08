"""撤销/重做功能的冒烟测试（offscreen 运行，不修改任何方案文件）。

运行前会临时清空 src/last_scheme_path.json（避免启动自动恢复旧方案干扰测试），
结束后自动还原其原始内容。
"""
import os
import sys
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

# 备份并临时清空“上次编辑方案”历史
last_file = Path(__file__).resolve().parent / "src" / "last_scheme_path.json"
_orig_last = last_file.read_text(encoding="utf-8") if last_file.exists() else None
last_file.write_text(json.dumps({"last_scheme_path": ""}), encoding="utf-8")

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.mainwindow import MainWindow

mw = MainWindow()
history = mw._history
assert history is not None, "撤销管理器未创建"

passed = 0
failed = 0

def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")

print("== 1. 节点增删 ==")
g0 = list(mw.timelineMainWidget.graph_list)
mw.timelineMainWidget.add_node(8)
g1 = list(mw.timelineMainWidget.graph_list)
check("新增节点后 graph_list 变长", len(g1) == len(g0) + 1)
check("can_undo 为 True", history.can_undo())
history.undo()
check("撤销后节点数恢复", len(mw.timelineMainWidget.graph_list) == len(g0))
check("can_redo 为 True", history.can_redo())
history.redo()
check("重做后节点数再次增加", len(mw.timelineMainWidget.graph_list) == len(g0) + 1)
# 撤销 ↔ 重做应可无限往复：重做步骤需回到撤销栈（重做后再撤销仍生效）
history.undo()
check("重做后再撤销仍生效", len(mw.timelineMainWidget.graph_list) == len(g0))
history.redo()
check("再次重做后节点数增加", len(mw.timelineMainWidget.graph_list) == len(g0) + 1)

print("== 2. 场地设置合并 ==")
scale0 = mw.scene.field_info.scale
mw.scene.field_info.set_scale(40)
mw.scene.field_info.set_scale(50)
mw.scene.field_info.set_scale(60)   # 同一参数连续修改应合并为一步
n_after_scale = len(history.undo_stack)
history.undo()
check("撤销后 scale 恢复", mw.scene.field_info.scale == scale0)
history.redo()
check("重做后 scale=60", mw.scene.field_info.scale == 60)

print("== 3. 会话（模拟绘图） ==")
scene = mw.scene
active = scene.active_node
n0 = len(scene.node_points[active])
history.begin("测试绘制")
pid = scene._next_point_id
scene.node_points[active].append({"id": pid, "x": 1.0, "y": 2.0, "group_id": None})
scene._next_point_id += 1
scene.point_lable.append({"prefix": "", "serial": pid + 1})
history.commit()
check("绘制后点位增加", len(scene.node_points[active]) == n0 + 1)
history.undo()
check("撤销后点位恢复", len(scene.node_points[active]) == n0)
check("撤销后 _next_point_id 恢复", scene._next_point_id == pid)
history.redo()
check("重做后点位恢复", len(scene.node_points[active]) == n0 + 1)

print("== 4. 会话取消不产生步骤 ==")
stack_n = len(history.undo_stack)
history.begin("取消测试")
history.cancel()
check("取消后撤销栈不变", len(history.undo_stack) == stack_n)

print("== 5. 撤销/重做恢复 UI 状态（工具/节点/选中） ==")
# 在节点 1（非 P0，旋转工具可用）放一个点位并选中，进入“旋转”会话
mw.timelineMainWidget.add_node(8)
scene.active_node = 1
mw.timelineMainWidget.selected_node = 1
mw.timelineMainWidget.current_beat = mw.timelineMainWidget.start_beat_of(1)
rot_pid = scene._next_point_id
scene.node_points[1].append({"id": rot_pid, "x": 0.0, "y": 0.0, "group_id": None})
scene._next_point_id += 1
scene.point_lable.append({"prefix": "", "serial": rot_pid + 1})
scene._selected_point_ids = {rot_pid}
mw._apply_active_tool("旋转")
mw._history.begin("旋转")
mw._history.commit()   # 空操作确认（仅验证 UI 状态快照）
ui = mw._history_capture()["ui"]
check("快照记录工具=旋转", ui["active_tool"] == "旋转")
check("快照记录选中点位", rot_pid in ui["selected_point_ids"])
history.undo()
check("撤销后工具=旋转（恢复快照工具）", mw.activeToolName == "旋转")
check("撤销后选中点位恢复", rot_pid in mw.scene._selected_point_ids)
# 还原为框选，避免残留会话
mw._history.cancel()
mw._apply_active_tool("框选")

print("== 6. 主菜单动作可用性 ==")
check("撤销菜单存在且可用", getattr(mw, "actionUndo", None) is not None and mw.actionUndo.isEnabled())

print("== 7. 应用设置合并与撤销 ==")
perf0 = mw.appSettingsDock._settings.get("performer_size")
mw.appSettingsDock._set("performer_size", 12.0)
mw.appSettingsDock._set("performer_size", 14.0)   # 连续修改同一参数 → 一步
history.undo()
check("撤销后应用设置 performer_size 恢复",
      abs(mw.appSettingsDock._settings["performer_size"] - perf0) < 1e-6)
history.redo()
check("重做后 performer_size=14",
      abs(mw.appSettingsDock._settings["performer_size"] - 14.0) < 1e-6)

print("== 8. 点位拖拽会话（按下→移动→松开） ==")
active = scene.active_node
pid = len(scene.node_points[active])          # 新增点位 id 与列表索引保持一致
if scene._next_point_id <= pid:
    scene._next_point_id = pid + 1
scene.node_points[active].append({"id": pid, "x": 1.0, "y": 1.0, "group_id": None})
scene.point_lable.append({"prefix": "", "serial": pid + 1})
scene._render_points_for_active_node()
scene._on_performer_point_pressed(pid)               # 按下 → begin（拖拽前快照）
pt = scene.node_points[active][pid]
pt["x"], pt["y"] = 5.0, 5.0                          # 拖拽中实时写回
scene._on_performer_point_released(pid, moved=True)  # 松开 → commit
check("拖拽后产生一步撤销", history.can_undo())
history.undo()
check("撤销后点位回到原位", scene.node_points[active][pid]["x"] == 1.0)
history.redo()
check("重做后点位在新位置", scene.node_points[active][pid]["x"] == 5.0)

# 还原被临时清空的历史文件
if _orig_last is not None:
    last_file.write_text(_orig_last, encoding="utf-8")

print(f"\n结果：通过 {passed} 项，失败 {failed} 项")
sys.exit(1 if failed else 0)
