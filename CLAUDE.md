# 豪猛健身教練 Bot 專案

## 專案概述
Jones 的個人 AI 健身教練系統。透過 Telegram Bot 提供健身問答、飲食記錄、InBody 分析、訓練日誌等功能，數據存入 Notion，由 Claude Sonnet 4.6 驅動。

---

## 系統架構

```
用戶 (Telegram)
    ↕
Oracle Cloud VM (Ubuntu 22.04, 24/7)
    ├── bot.py      ← 主程式
    ├── morning.py  ← cron 09:00 台灣時間
    └── evening.py  ← cron 22:00 台灣時間
         ↕
Claude Sonnet 4.6 (Anthropic API + Tool Use)
         ↕
Notion 資料庫（飲食、InBody、訓練日誌、動作資料庫）
```

---

## 環境變數（存於 .env，不進 git）

| 變數名 | 說明 |
|--------|------|
| `ANTHROPIC_KEY` | Anthropic API Key |
| `BOT_TOKEN` | Telegram Bot Token |
| `NOTION_TOKEN` | Notion Integration Token |
| `TELEGRAM_CHAT_ID` | 接收訊息的用戶 Chat ID |

Notion 資料庫 ID 與 VM 連線資訊請查閱 memory 檔案。

---

## 部署工作流程

```bash
# 更新 bot 程式
scp -i SSH_KEY bot_cloud.py ubuntu@VM_IP:/home/ubuntu/bot.py
ssh -i SSH_KEY ubuntu@VM_IP "sudo systemctl restart fitness-bot"

# 更新排程腳本
scp -i SSH_KEY morning.py evening.py ubuntu@VM_IP:/home/ubuntu/

# 查看 log
ssh -i SSH_KEY ubuntu@VM_IP "sudo journalctl -u fitness-bot -n 50"

# 測試早報
ssh -i SSH_KEY ubuntu@VM_IP "python3 /home/ubuntu/morning.py"
```

---

## Bot 功能

### 自動偵測
| 輸入 | 行為 |
|------|------|
| `早餐 燕麥雞蛋` | 存飲食記錄 + Claude 分析營養 |
| 組數格式訓練資料 | 存訓練日誌 + 動作資料庫 + 自動填訓練部位 |
| InBody 照片 | 解析數值 + 存 Notion |
| 食物照片 | Claude 分析營養成分 |
| 一般文字 | Claude Tool Use（可查詢/修改 Notion）|

### 指令
| 指令 | 功能 |
|------|------|
| `/today` | 查今日飲食紀錄 |
| `/goal` | 查碳循環目標 |
| `/report [內容]` | 晚間回報，存 Notion |

### Claude Tool Use
- `query_notion` — 查詢資料庫（無日期時 fallback 抓最近 5 筆）
- `update_notion_page` — 更新欄位
- `delete_notion_page` — 刪除頁面
- `save_diet_record` — 存飲食
- `save_inbody_record` — 存 InBody

---

## 碳水循環目標

| 日類別 | 碳水 | 蛋白質 | 脂肪 | 熱量 |
|--------|------|--------|------|------|
| 低碳日 | 100g | 240g | 100g | 2260kcal |
| 中碳日 | 250g | 200g | 60g | 2340kcal |
| 高碳日 | 400g | 160g | 30g | 2510kcal |

> 六月正式啟動，五月暫停

補水目標：3000cc／訓練重點：倒三角／營養品：乳清、肌酸、BCAA、魚油、維他命、ZMA

---

## 遇過的問題與解決方式

### SSL 問題（Windows 本機）
**問題：** `python-telegram-bot` 使用 httpx，Windows 機器 SSL 驗證失敗  
**解法：** 改用 `pyTelegramBotAPI`（底層用 requests）；Anthropic SDK 傳入 `http_client=httpx.Client(verify=False)`

### Tool 屬性名不能用中文
**問題：** Anthropic API tool input_schema property key 必須符合 `^[a-zA-Z0-9_.-]{1,64}$`  
**解法：** `save_inbody_record` 欄位改英文（weight、bmi 等），execute_tool 內部 map 回中文

### Notion 資料庫 404
**問題：** 用 collection ID 呼叫 Notion REST API 會 404  
**解法：** 用資料庫的 page URL ID（Notion search 回傳的 `id`）

### Notion 資料庫需授權 Integration
**問題：** 新資料庫預設未授權給 Notion integration  
**解法：** 資料庫頁面 → ⋯ → Connections → 加入 Claude Code Space  
**例外：** 繼承上層頁面權限時可能已自動授權（API 回傳 200 即可）

### 訓練部位欄位為空
**問題：** 儲存訓練日誌未自動填 訓練部位  
**解法：** `notion_create_workout_log` 儲存完 Set Log 後，查詢動作資料庫取得主要訓練部位，去重後填入

### Claude Tool Use 查詢日期不符
**問題：** 查「昨天訓練」但訓練記錄在前天，回傳空  
**解法：** `query_notion` 指定日期查無結果時，自動 fallback 抓最近 5 筆

### Bot 無對話記憶
**問題：** 每則訊息獨立處理，無法理解上下文  
**解法：** `conv_history` dict 每個 chat_id 保留最近 10 則，每次呼叫 Claude 帶完整歷史

### Claude 說無法存取 Notion
**問題：** System prompt 未告知 Claude 有 Notion 操作能力  
**解法：** System prompt 加入「你擁有讀寫 Notion 資料庫的能力（透過 bot 自動執行）」

---

## 注意事項

- 雲端 VM 已接手，本機 bot 通常不需要跑
- 修改功能改 `bot_cloud.py`，scp 上傳覆蓋 VM 的 `bot.py` 後重啟
- Tool 屬性名只能用英數字和底線
- 對話歷史存在記憶體，VM 重啟後清空（正常現象）
