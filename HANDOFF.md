# 交接：ok-kes 擬人化改造

這個 fork（`KevinTseng29/ok-kes`）的目標：把卡厄思夢境自動化工具的輸入與行為往 AzurLaneAutoScript（ALAS）的擬人化做法靠攏，主要在 MuMu 模擬器上使用。

工作分支：`humanize-input`（不要推 master）。

## 協作規則

- commit **不要加** `Co-Authored-By` 或任何 Claude 署名。作者用 `KevinTseng29`。
- 只推到 `KevinTseng29/ok-kes` 的功能分支。
- 盡量把改動集中在新模組，別改原作者那 86 處 `click_box` 呼叫，方便之後從上游 `baoxin1100/ok-kes` 同步。
- 不要在各模式的 `default_config` 加新欄位：`config_sync.py` 會把配置上傳到作者的雲端做熱門配置統計，新欄位會跟著上傳，也可能影響配置碼的匯入匯出。設定集中放在 `ok_tasks/humanize.py` 的 `HUMANIZE`。

## 執行環境

- 遊戲：卡厄思夢境國際服，跑在 **MuMu 模擬器**上（`C:\Program Files\Netease\MuMuPlayer`）。ok-kes 走 MuMu 的 nemu_ipc 截圖與輸入。
- MuMu 有**老闆鍵 Alt+Q**，會隱藏所有 MuMu 視窗。之前「MuMu 開不起來」其實是視窗被藏起來，程序一直在背景跑。日誌在 `%APPDATA%\Netease\MuMuPlayerGlobal\logs\nx_main.log`。
- MuMu 內：解析度 16:9（建議 1920×1080），刪掉手牌區的數字鍵映射。
- 遊戲內：開啟快捷鍵顯示、自動戰鬥、自動劇情；ok-kes 的遊戲語言設成繁體中文。
- 從原始碼執行：`pip install -r requirements.txt`，然後 `python main.py`（除錯版用 `python main_debug.py`）。
- 測試：`python -m unittest tests/test_humanize.py`

## 已確認的技術事實

- ok-kes 用的框架是 **`ok-script-kes==1.0.3`**（PyPI 上的分支套件），不是上游 `ok-script`。看框架原始碼要看這個版本。
- 任務檔放在 `ok_tasks/`，由框架的 TaskManager 用 glob 載入，並把資料夾加進 `sys.path`，所以模組之間是平的匯入（`import utils_chaos`）。載入器只會挑 `BaseTask`／`TriggerTask` 的子類別當任務，`humanize.py` 不會被誤載。
- PC 版設定是 `interaction: ['PostMessage']`、截圖 `WGC → BitBlt_RenderFull → BitBlt`、`require_bg: True`。PostMessage 只是往視窗送訊息，不是系統層輸入，容易被分辨，所以改用模擬器。
- 在 nemu_ipc 路徑上，框架**本來就有** ALAS 的兩項做法：
  - `click_nemu_ipc` 的按壓時間是 10～20ms 隨機
  - `swipe_nemu` 用 ALAS 的 `insert_swipe` 貝茲曲線
  - 但 `AdbInteraction.click` 會忽略傳進去的 `down_time`，也不會隨機化點擊位置。
- 原版的 `click_box` 用 `Box.relative_with_variance`，偏移只有 0～0.1 像素，等於每次都點正中心；點完固定 `after_sleep=1`。
- 主迴圈：`TriggerTask`、`trigger_interval=1`，每輪先做全畫面 OCR，再依序跑 `PAGE_HANDLERS`，第一個命中的 handler 就結束這一輪。
- 卡住處理在 `utils.handle_stuck_log`：畫面 10 秒沒變化時，會依序嘗試關閉頁面、處理特殊怪物、**隨機點一張卡**、處理未知頁面，而且無限重試。

## 已完成（commit `ebf1711`）

`ok_tasks/humanize.py` 的 `HumanizeMixin`，已套用到 ChaosMode、SortieMode、StoryMode、GetMengbian、TestTrigger（mixin 必須放在第一個繼承位置）：

- `click_box`：在方框中心 60% 的範圍內，以近似常態分布取點（同 ALAS，用 3 個均勻亂數取平均）；小於 6 像素的框直接點中心。
- 固定座標的 `click`（含相對座標）：加 ±0.3% 畫面寬的抖動（1920 寬約 6 像素）。
- 點擊前有反應延遲 0.05～0.25 秒，3% 機率再多停頓 0.5～1.8 秒；點擊後的 `after_sleep` 乘上 0.85～1.35。
- `down_time` 隨機 0.04～0.11 秒（只有 PC 路徑會生效）。
- `swipe_relative` 的端點加抖動，持續時間乘上 0.85～1.25。
- `send_key`、`mouse_down` 也做了隨機化。
- `HUMANIZE.enabled = False` 會讓所有方法直接交給原本的實作。
- `tests/test_humanize.py`：12 個測試，用假的 base class 驗證，不需要安裝 ok 套件。

**尚未接真實遊戲測試過。**

## 下一步（依優先順序）

1. **實測**：在 MuMu 上跑卡厄思模式和出擊模式，確認流程沒被改壞（特別是小按鈕、拖卡牌到敵人身上、長按看人格面具卡），再依 log 調整參數。注意反應延遲會讓每輪變慢一點。
2. **連點保護**（ALAS 的 `module/device/device.py` 的 `click_record`）：用 deque 記最近 15 次點擊的目標名稱。同一個目標 ≥12 次，或兩個目標來回各 ≥6 次，就判定異常：先嘗試回到已知頁面，還是不行就停止任務。可以放進 mixin 的 `click`。
3. **同目標冷卻**（ALAS 的 `appear(button, interval=N)`）：同一個目標名稱 N 秒內不要再點。
4. **作息節奏**：連續執行上限、每輪之間隨機休息、可選的執行時段。ALAS 的排程器（`next_run`、`ServerUpdate`、`WhenTaskQueueEmpty`）太重，做輕量版就好。
5. **失敗策略**：`handle_stuck_log` 的兜底連續觸發 N 次就停止並通知，取代「隨機點卡牌」。
6. （可選）在 nemu_ipc 路徑把點擊改成 `mouse_down → sleep(人類按壓時間) → mouse_up`，取代框架固定的 10～20ms。

## 參考

- ALAS：https://github.com/LmeSzinc/AzurLaneAutoScript
  - `module/base/utils.py`：`random_rectangle_point`、`random_normal_distribution_int`
  - `module/device/method/minitouch.py`：`insert_swipe`（貝茲曲線）
  - `module/device/device.py`：`click_record`、`stuck_record`
  - `alas.py`：失敗 3 次就要求人工接手、遇到 GameStuck 就重啟遊戲
- 上游 ok-kes：https://github.com/baoxin1100/ok-kes
- 框架：PyPI 的 `ok-script-kes 1.0.3`（上游：https://github.com/ok-oldking/ok-script）

## 風險提醒

國際服（STOVE）定期公告永久封鎖使用自動化程式的帳號，例如 2026/10/23 那一波 811,466 個帳號，主要是多開和工作室；國服的服務條款也禁止未授權的第三方程式。擬人化只能降低「點擊太規律」這類特徵，沒辦法讓自動化變得不可偵測。
