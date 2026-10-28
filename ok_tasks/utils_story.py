import re
import time

from ok import TriggerTask

from dialogue import auto_chat_speed
from utils import (
    _move_and_click,
    handle_center_confirm,
    handle_confirm,
    handle_enter,
    handle_close_page,
    handle_next_step,
    handle_event_task,
    find_box_at_point,
)
from utils_chaos import handle_battle_auto_check


# ------------------------- 页面处理函数 -------------------------

def handle_story_complete(task: TriggerTask):
    """精确匹配剧情页面右下区域的完成按钮。"""
    complete_box = next(
        (
            box for box in task.all_texts
            if box.name.strip() == "完成"
            and 0.380 <= (box.x + box.width / 2) / task.width <= 0.995
            and 0.882 <= (box.y + box.height / 2) / task.height <= 0.990
        ),
        None,
    )
    if complete_box:
        task.log_info("检测到剧情完成按钮，点击完成")
        _move_and_click(
            task,
            (complete_box.x + complete_box.width / 2) / task.width,
            (complete_box.y + complete_box.height / 2) / task.height,
        )
        task.sleep(1)
        return True
    return False


def handle_close_dialog(task: TriggerTask):
    """关闭剧情对话弹窗。"""
    close_dialog = task.find_one(
        feature_name="close_dialog",
        box=task.box_of_screen(0.598, 0.007, 0.997, 0.424),
        threshold=0.90,
    )
    if close_dialog:
        task.log_info("检测到剧情对话关闭按钮，点击关闭")
        _move_and_click(
            task,
            (close_dialog.x + close_dialog.width / 2) / task.width,
            (close_dialog.y + close_dialog.height / 2) / task.height,
        )
        task.sleep(1)
        return True
    return False


def find_auto_chat(task: TriggerTask):
    """找右上角的自动对话按钮，回传 (按钮, 状态)；状态见 dialogue.auto_chat_speed，没有按钮回传 (None, None)。"""
    search_box = task.box_of_screen(0.655, 0.007, 0.996, 0.097)
    # 一倍速的置信度最低约 0.79，低于框架默认门槛 0.8；其他图标误判都在 0.7 以下
    auto_chat = task.find_one(
        feature_name=["autochatenable", "autochatenable2"], box=search_box, threshold=0.75
    )
    if not auto_chat:
        return None, None
    icon = task.frame[auto_chat.y:auto_chat.y + auto_chat.height, auto_chat.x:auto_chat.x + auto_chat.width]
    state = auto_chat_speed(icon)
    return (auto_chat, state) if state else (None, None)


def handle_auto_chat(task: TriggerTask):
    """自动对话：按钮每点一次在「未开启 → 一倍速 → 最快倍速」之间循环。
    已是最快倍速就不点；未开启或一倍速才点，点到最快为止。
    （模板置信度会随背景浮动，最快倍速也常低于旧门槛 0.96，被当成没开而点掉，所以改看箭头颜色。）"""
    auto_chat, state = find_auto_chat(task)
    if state not in ("off", "slow"):
        return False
    task.log_info(f"自动对话{'未开启' if state == 'off' else '为一倍速'}，点击切到最快倍速")
    _move_and_click(
        task,
        (auto_chat.x + auto_chat.width / 2) / task.width,
        (auto_chat.y + auto_chat.height / 2) / task.height,
    )
    # 等按钮切换完再看下一帧，避免动画中途又点一次跳回未开启
    task.sleep(1)
    return True


def handle_view_event(task: TriggerTask):
    """查看事件页面: 在指定区域检测check或check2特征并点击。"""
    search_box = task.box_of_screen(0.084, 0.125, 0.995, 0.875)
    check_box = task.find_one(feature_name=["check", "check2"], box=search_box)
    if check_box:
        task.log_info(f"检测到查看事件，点击{check_box.name}特征")
        _move_and_click(
            task,
            (check_box.x + check_box.width / 2) / task.width,
            (check_box.y + check_box.height / 2) / task.height,
        )
        task.sleep(0.5)
        return True
    return False


# def handle_team_config(task: TriggerTask):
#     """队伍配置页面: 检测(0.122,0.047)处'配置队伍'文本，选择空槽位补充角色。"""
#     title_box = find_box_at_point(task, 0.122, 0.047)
#     if not (title_box and "配置队伍" in title_box.name):
#         return False
#     task.log_info("检测到队伍配置页面")
#     slots = [
#         (0.057, 0.611, 0.132, 0.456),
#         (0.270, 0.610, 0.344, 0.444),
#         (0.484, 0.608, 0.554, 0.436),
#     ]
#     for check_x, check_y, click_x, click_y in slots:
#         box = find_box_at_point(task, check_x, check_y)
#         if box is None or not box.name.strip():
#             task.log_info(f"槽位({check_x},{check_y})为空，点击({click_x},{click_y})补充角色")
#             _move_and_click(task, click_x, click_y)
#             task.sleep(2)
#             return True
#     task.log_info("所有槽位已有角色，无需补充")
#     return False


def handle_enter_stage(task: TriggerTask):
    """入场按钮: 检测(0.820,0.931)位置的入场按钮并点击。"""
    box = find_box_at_point(task, 0.820, 0.931)
    if box and "入场" in box.name:
        task.log_info("检测到入场按钮，点击入场")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


_TEAM_ENTER_TRIES = 3  # 配置队伍页连点几次进入没反应就停
_TEAM_ENTER_RETRY_AFTER = 30  # 停下后隔多久再试一次


def handle_team_enter(task: TriggerTask):
    """配置队伍页面的进入按钮。队伍没配满时游戏不让进，点了没反应也没有提示；
    连点几次还停在这页就提醒手动配置队伍，之后隔一段时间才再点一次（配好了就进得去）。"""
    title = find_box_at_point(task, 0.122, 0.047)
    if not (title and "配置队伍" in title.name):
        task._team_enter_clicks = 0
        return False
    clicks = getattr(task, "_team_enter_clicks", 0)
    if clicks >= _TEAM_ENTER_TRIES and time.time() - task._team_enter_last_click < _TEAM_ENTER_RETRY_AFTER:
        return True  # 等手动配置队伍，这段时间不点
    if not handle_enter(task):
        return False
    task._team_enter_clicks = clicks + 1
    task._team_enter_last_click = time.time()
    if task._team_enter_clicks == _TEAM_ENTER_TRIES:
        task.log_info(
            f"配置队伍页面点了{_TEAM_ENTER_TRIES}次进入都没反应，可能队伍没配满，"
            f"请手动配置队伍（每{_TEAM_ENTER_RETRY_AFTER}秒再试一次）",
            notify=True,
        )
    return True


def handle_enter_story_or_battle(task: TriggerTask):
    """故事/战斗入口页面: 点击最左侧的enterstory或enterbattle特征。"""
    search_box = task.box_of_screen(0.085, 0.124, 0.995, 0.874)
    story_boxes = task.find_feature(feature_name="enterstory", box=search_box)
    battle_boxes = task.find_feature(feature_name="enterbattle", box=search_box, threshold=0.85)
    candidates = [
        *((box, "故事") for box in story_boxes),
        *((box, "战斗") for box in battle_boxes),
    ]
    if candidates:
        chosen_box, entrance_type = min(candidates, key=lambda item: item[0].x)
        task.log_info(
            f"检测到{entrance_type}入口，点击最左侧特征"
            f"（x={chosen_box.x}, confidence={chosen_box.confidence:.2f}）"
        )
        task.click_box(chosen_box)
        # 这一章还有关卡可进，翻章的记录重来
        task._story_switched_from = task._story_chapter_blocked = None
        task.sleep(2)
        return True
    return False


_NEXT_CHAPTER = (0.746, 0.044)  # 故事地图顶部章节列右侧的 ▷
_PREV_CHAPTER = (0.260, 0.044)  # 左侧的 ◁
# 同一章地图上连续这么久都没有可进入的关卡才翻章：打完关卡回到地图时有解锁动画，入口会晚几秒才出现
_CHAPTER_IDLE_SECONDS = 10
_CHAPTER_IDLE_GAP = 5  # 两帧相隔超过这么久（中间在别的页面）就重新计时


def _story_map_chapter(task: TriggerTask):
    """在故事地图（左上「故事」、顶部中间章节名）上回传当前章节名，例如「序章」「第1章」；不是故事地图回传 None。"""
    def in_header(box, x1, x2):
        cx = (box.x + box.width / 2) / task.width
        cy = (box.y + box.height / 2) / task.height
        return x1 <= cx <= x2 and cy <= 0.09

    if not any(box.name.strip() == "故事" and in_header(box, 0.0, 0.2) for box in task.all_texts):
        return None
    for box in task.all_texts:
        match = re.search(r"序章|第\s*\d+\s*章", box.name)
        if match and in_header(box, 0.4, 0.6):
            return re.sub(r"\s", "", match.group())
    return None


def handle_next_chapter(task: TriggerTask):
    """故事地图上这一章的关卡都完成了（没有可进入的关卡）就点顶部 ▷ 切到下一章。
    排在最后：前面的处理函数都没命中、同一章持续一段时间都是这样才翻。只往后翻一章：
    翻了章节名没变（最后一章或还没开放）就停手提醒；下一章也没有关卡可点（可能原本那章还有卡厄思关卡
    或画面外的关卡）就点 ◁ 切回原本那章再提醒，不一直往后翻。"""
    chapter = _story_map_chapter(task)
    now = time.time()
    since = getattr(task, "_story_idle_since", now)
    if (chapter is None or chapter != getattr(task, "_story_idle_chapter", None)
            or now - getattr(task, "_story_idle_at", 0) > _CHAPTER_IDLE_GAP):
        since = now  # 换了章节（地图刚载入）或中间在别的页面，重新计时
    task._story_idle_at, task._story_idle_chapter, task._story_idle_since = now, chapter, since
    if chapter is None or now - since < _CHAPTER_IDLE_SECONDS or chapter == getattr(task, "_story_chapter_blocked", None):
        return False
    switched_from = getattr(task, "_story_switched_from", None)
    if chapter == switched_from:
        task._story_chapter_blocked = chapter
        task.log_info(f"故事地图{chapter}没有可进入的关卡，也切不到下一章，请手动处理", notify=True)
        return False
    task._story_idle_chapter = None  # 点了之后重新计时
    if switched_from:
        task.log_info(f"下一章{chapter}也没有可进入的关卡，切回{switched_from}，请手动处理", notify=True)
        _move_and_click(task, *_PREV_CHAPTER)
        task._story_chapter_blocked = switched_from
        task.sleep(2)
        return True
    task.log_info(f"故事地图{chapter}没有可进入的关卡，点击 ▷ 切到下一章")
    _move_and_click(task, *_NEXT_CHAPTER)
    task._story_switched_from = chapter
    task.sleep(2)
    return True


def handle_skip_story(task: TriggerTask):
    """可跳过剧情页面: 检测到skipstory特征则点击跳过。"""
    boxes = task.find_feature(feature_name="skipstory")
    if boxes:
        task.log_info("检测到可跳过剧情页面，点击跳过")
        task.click_box(boxes[0])
        task.sleep(1)
        return True
    return False


def handle_observe(task: TriggerTask):
    """观测卡厄思关卡页面: 在区域内检测文本'观测'并点击。"""
    x1, y1, x2, y2 = 0.092, 0.214, 0.962, 0.792
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if x1 <= cx <= x2 and y1 <= cy <= y2 and b.name.strip() == "观测":
            task.log_info("检测到观测卡厄思关卡，点击观测")
            task.click_box(b)
            task.sleep(4)
            return True
    return False


# 剧情模式页面处理函数列表（按优先级排序）
PAGE_HANDLERS = [
    handle_center_confirm,  #页面中央确认按钮（最高优先级）
    handle_story_complete,  #剧情完成按钮（高优先级）
    # handle_team_config,  #队伍配置（最高优先级）
    handle_skip_story,  #跳过剧情
    handle_view_event,  #查看事件
    handle_confirm,  #确认按钮
    handle_team_enter,  #配置队伍页的进入按钮（队伍没配满就停手提醒）
    handle_enter,  #进入按钮
    handle_enter_stage,  #入场按钮
    handle_close_page,  #点击屏幕关闭页面
    handle_enter_story_or_battle,
    handle_observe,  #观测卡厄思关卡
    handle_next_step,
    handle_battle_auto_check,  #自动战斗检测
    handle_event_task,  #事件任务（倒数第三优先级）
    handle_auto_chat,  #自动对话检查（倒数第二优先级）
    handle_close_dialog,  #关闭剧情对话弹窗
    handle_next_chapter,  #这一章打完切到下一章（最低优先级）
]
