"""整层大地图：路线选择页点小地图右上角的放大镜打开整层地图，左右滑动截完整层，
辨识所有节点、特殊标志与连线，产生和 recognize_map_connections 同样格式的 map_info，
交给 find_best_map_route_by_priority 规划整层路线。

只做辨识，不点击；打开、滑动、关闭由 utils.scan_big_map 负责。坐标以 1280x720 为基准，
其他分辨率先缩放到这个尺寸再辨识。
"""
import os

import cv2
import numpy as np

BASE_W, BASE_H = 1280, 720
ZOOM_IN = (0.395, 0.656)  # 路线选择页：小地图右上角的放大镜
ZOOM_OUT = (0.081, 0.930)  # 大地图：左下角的缩小按钮
ROW_Y = (150, 258, 366, 474, 582)  # 五排节点的中心
COLUMN_STEP = 164  # 相邻两列的水平距离
LINE_Y_OFFSET = 8  # 连线接在菱形中心下方一点
LINE_X_INSET = 54  # 连线从菱形左右两个角出发

_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "big_map")
_templates = {}


def _template(name):
    if name not in _templates:
        _templates[name] = cv2.imread(os.path.join(_ASSET_DIR, f"{name}.png"))
    return _templates[name]


def normalize(frame):
    """缩放到 1280x720。"""
    if frame is None:
        return None
    if frame.shape[1] != BASE_W or frame.shape[0] != BASE_H:
        return cv2.resize(frame, (BASE_W, BASE_H))
    return frame


def is_open(frame):
    """左下角有「缩小」按钮就是大地图开着。"""
    frame = normalize(frame)
    if frame is None:
        return False
    result = cv2.matchTemplate(frame[600:720, 0:300], _template("zoom_out"), cv2.TM_CCOEFF_NORMED)
    return float(result.max()) > 0.8


def frame_offset(previous, current):
    """current 相对 previous 往右多看到了多少像素（previous 的 x = current 的 x + 位移）。
    用 previous 最右边的一条带子在 current 里找位置（滑动约 800 像素后它还在画面里）；
    找不到回传 None，没动回传 0。"""
    strip = previous[120:620, 900:1200]
    result = cv2.matchTemplate(current, strip, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    if score < 0.7:
        return None
    return 900 - location[0]


def find_pin(frame):
    """目前位置的定位图钉；回传图钉下方节点的中心 (x, 排序号)，找不到回传 None。"""
    template = _template("pin")
    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    if score < 0.8:
        return None
    pin_x = location[0] + template.shape[1] // 2
    pin_bottom = location[1] + template.shape[0]
    row = min(range(len(ROW_Y)), key=lambda index: abs(ROW_Y[index] - (pin_bottom + 18)))
    return pin_x, row


def _face_hsv(frame, x, y):
    patch = frame[y - 4:y + 5, x - 34:x - 20]
    if patch.size == 0:
        return None
    mean = patch.reshape(-1, 3).mean(axis=0).astype(np.uint8).reshape(1, 1, 3)
    return cv2.cvtColor(mean, cv2.COLOR_BGR2HSV)[0, 0]


def _orange_kind(frame, x, y):
    """橘色菱形：火焰是休息、结晶是结算。"""
    crop = frame[y - 22:y + 18, x - 20:x + 20]
    scores = {}
    for name, node_type in (("flame", "休息"), ("settle", "结算")):
        template = _template(name)
        if crop.shape[:2] != template.shape[:2]:
            return "休息"
        scores[node_type] = float(cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)[0, 0])
    return max(scores, key=scores.get)


def classify_node(frame, x, y):
    """格子 (x, y) 上的节点类型；没有节点回传 None。"""
    hsv = _face_hsv(frame, x, y)
    if hsv is None:
        return None
    hue, saturation, value = (int(v) for v in hsv)
    # 菱形本身饱和又亮（可选那一列罩着青色光带，饱和度会降到 130 左右）；
    # 光带本身较暗（亮度约 95），不算节点
    if saturation < 110 or value < 105:
        return None
    if hue <= 30:
        return _orange_kind(frame, x, y)
    if 85 <= hue <= 118:
        return "事件"
    if 120 <= hue <= 152:
        return "精英"
    if hue >= 153:
        return "小怪"
    return None


def special_features(frame, x, y, node_type):
    """菱形右上角的徽章：米色店面是商店（休息点以外的米色徽章当成卡厄思标志）、紫色火焰是困难。"""
    blue, green, red = frame[y - 42:y - 22, x + 26:x + 44].reshape(-1, 3).mean(axis=0)
    if blue > 170 and blue - green > 40:  # 紫色火焰（BGR 约 221,145,188）
        return [{"feature_name": "hard_in_map", "priority": -1}]
    if red > 150 and green > 130 and red - blue > 25:  # 米色徽章（BGR 约 129,166,183）
        name = "shop_in_map" if node_type == "休息" else "kalei_in_map"
        return [{"feature_name": name, "priority": 1}]
    return []


def line_ratio(frame, start, end):
    """两点之间白色连线的覆盖率。"""
    hits = total = 0
    for t in np.linspace(0.15, 0.85, 15):
        px = int(round(start[0] + (end[0] - start[0]) * t))
        py = int(round(start[1] + (end[1] - start[1]) * t))
        window = frame[max(0, py - 3):py + 4, max(0, px - 1):px + 2]
        if window.size == 0:
            continue
        total += 1
        if int(window.min(axis=2).max()) > 150:
            hits += 1
    return hits / total if total else 0.0


def parse_big_map(frames, line_threshold=0.6):
    """把左右滑动截下的几张大地图拼起来辨识。回传 map_info（nodes、adjacency、connections），
    目前位置的节点 type 是「当前位置」；只收目前位置以右的节点。找不到图钉回传 None。"""
    frames = [normalize(frame) for frame in frames if frame is not None]
    if not frames:
        return None
    offsets = [0]
    for previous, current in zip(frames, frames[1:]):
        delta = frame_offset(previous, current)
        if delta is None:
            break
        offsets.append(offsets[-1] + delta)
    frames = frames[:len(offsets)]

    pin = None
    for frame, offset in zip(frames, offsets):
        found = find_pin(frame)
        if found:
            pin = (found[0] + offset, found[1])
            break
    if pin is None:
        return None
    pin_x, pin_row = pin

    def view(global_x, margin=70):
        """看得到这个全域 x 的那一张，选最靠画面中间的。"""
        best = None
        for frame, offset in zip(frames, offsets):
            local_x = global_x - offset
            if margin <= local_x <= BASE_W - margin:
                distance = abs(local_x - BASE_W / 2)
                if best is None or distance < best[0]:
                    best = (distance, frame, local_x)
        return (best[1], best[2]) if best else (None, None)

    nodes = [{"id": 0, "type": "当前位置", "column": 0, "slot": pin_row, "row": 1,
              "x": pin_x, "y": ROW_Y[pin_row], "special_features": [], "special_priority": 0}]
    column = 1
    while True:
        global_x = pin_x + COLUMN_STEP * column
        frame, local_x = view(global_x)
        if frame is None:
            break
        found = []
        for slot, y in enumerate(ROW_Y):
            node_type = classify_node(frame, local_x, y)
            if node_type:
                specials = special_features(frame, local_x, y, node_type)
                found.append({"type": node_type, "column": column, "slot": slot, "x": global_x, "y": y,
                              "special_features": specials,
                              "special_priority": sum(item["priority"] for item in specials)})
        if not found:
            break  # 这一列没有节点：到 boss 了
        for row, node in enumerate(found, start=1):
            node["row"] = row
            node["id"] = len(nodes)
            nodes.append(node)
        column += 1

    adjacency = {node["id"]: [] for node in nodes}
    connections = []
    for first in nodes:
        for second in nodes:
            if second["column"] != first["column"] + 1:
                continue
            frame, local_x = view((first["x"] + second["x"]) / 2, margin=COLUMN_STEP // 2 + 10)
            if frame is None:
                continue
            left_x = int(local_x - COLUMN_STEP / 2 + LINE_X_INSET)
            right_x = int(local_x + COLUMN_STEP / 2 - LINE_X_INSET)
            ratio = line_ratio(frame, (left_x, first["y"] + LINE_Y_OFFSET), (right_x, second["y"] + LINE_Y_OFFSET))
            if ratio >= line_threshold:
                adjacency[first["id"]].append(second["id"])
                connections.append({"from": first["id"], "to": second["id"], "brightness_ratio": ratio})
    return {"nodes": nodes, "adjacency": adjacency, "connections": connections}


def describe(map_info):
    """给日志用的简短描述：每列「排号:类型(+标志)」。"""
    columns = {}
    for node in map_info["nodes"]:
        tag = node["type"] + "".join(
            "+" + item["feature_name"].removesuffix("_in_map") for item in node["special_features"])
        columns.setdefault(node["column"], []).append(f"{node['slot']}:{tag}")
    return " | ".join(f"第{column}列 " + " ".join(items) for column, items in sorted(columns.items()))
