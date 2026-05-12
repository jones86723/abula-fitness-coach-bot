import logging
import base64
import json
import re
import os
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
import requests
import anthropic
import telebot
import httpx

load_dotenv()

ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]
BOT_TOKEN     = os.environ["BOT_TOKEN"]
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_DIET_DB    = "30e0ef30240a804995f3d8154d4aec90"
NOTION_INBODY_DB  = "3f9cf4f23f254b23b702c5d8bb19b016"
NOTION_HABITS_DB  = "3f9cf4f23f254b23b702c5d8bb19b016"
NOTION_WORKOUT_DB = "30a0ef30240a8023a4c7f55dafbdd588"
NOTION_SETLOG_DB  = "30a0ef30240a80739a41f3e3b83aab8b"
NOTION_EXLIB_DB   = "30a0ef30240a80509ccfdfc4c07ad9bb"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}
MEAL_EMOJI = {"早餐": "🌅", "午餐": "☀️", "晚餐": "🌙", "練前": "🏋️"}
MEAL_MAP   = {
    "早餐": "早餐", "午餐": "午餐", "中餐": "午餐",
    "晚餐": "晚餐", "練前": "練前",
    "早": "早餐", "午": "午餐", "晚": "晚餐",
}
SYSTEM_PROMPT = """你是「豪猛教練」，一位專業的健美/健體競賽訓練教練。

學員資訊：
- 目標：健體競賽（倒三角體型）、碳水循環飲食
- 碳循環目標（六月正式啟動，五月暫停）：
    低碳日：碳水100g、蛋白質240g、脂肪100g = 2260kcal
    中碳日：碳水250g、蛋白質200g、脂肪60g  = 2340kcal
    高碳日：碳水400g、蛋白質160g、脂肪30g  = 2510kcal
- 每日補水目標：3000cc
- 訓練重點：倒三角（背寬、肩膀、胸部）
- 營養品：乳清蛋白、肌酸、BCAA、魚油、綜合維他命、ZMA

你擁有的能力（透過 bot 自動執行，不需要請用戶手動操作）：
- 讀寫 Notion 資料庫：飲食紀錄、InBody 身體數據、訓練日誌、動作資料庫
- 自動存入、查詢、修改、合併 Notion 紀錄
- 分析照片（食物、InBody 報告）

回答原則：
- 用繁體中文，語氣專業但親切
- 健身動作問題：給出正確要領、常見錯誤、訓練建議
- 飲食/食物問題：估算蛋白質、碳水、脂肪、總熱量，評估是否符合目標
- 看到食物照片：辨識食物、估算宏量營養素
- 用戶要求修改或合併 Notion 資料時，直接告知已操作完成，不要叫用戶手動進 Notion
- 回答簡潔實用"""

ai  = anthropic.Anthropic(api_key=ANTHROPIC_KEY, http_client=httpx.Client(verify=False))
bot = telebot.TeleBot(BOT_TOKEN)

# 對話歷史
conv_history = defaultdict(list)

# Notion 資料庫對應表
DB_MAP = {
    "飲食紀錄": "30e0ef30240a804995f3d8154d4aec90",
    "身體數據": "3f9cf4f23f254b23b702c5d8bb19b016",
    "訓練日誌": "30a0ef30240a8023a4c7f55dafbdd588",
    "動作資料庫": "30a0ef30240a80509ccfdfc4c07ad9bb",
    "單組紀錄": "30a0ef30240a80739a41f3e3b83aab8b",
}

# Claude 工具定義
TOOLS = [
    {
        "name": "query_notion",
        "description": "查詢 Notion 資料庫中的記錄，可依日期篩選",
        "input_schema": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "enum": ["飲食紀錄", "身體數據", "訓練日誌", "動作資料庫"],
                    "description": "要查詢的資料庫"
                },
                "date": {
                    "type": "string",
                    "description": "日期篩選，格式 YYYY-MM-DD（可選）"
                }
            },
            "required": ["database"]
        }
    },
    {
        "name": "update_notion_page",
        "description": "更新 Notion 頁面的數值或文字欄位",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "頁面 ID"},
                "fields": {
                    "type": "object",
                    "description": "要更新的欄位，例如 {\"體重\": 80.5, \"體脂率\": 20.1}"
                }
            },
            "required": ["page_id", "fields"]
        }
    },
    {
        "name": "delete_notion_page",
        "description": "刪除（封存）Notion 中的頁面記錄",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "要刪除的頁面 ID"}
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "save_diet_record",
        "description": "儲存一筆飲食記錄到 Notion",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_time": {"type": "string", "enum": ["早餐", "午餐", "晚餐", "練前"]},
                "food": {"type": "string"},
                "date_label": {"type": "string", "description": "日期標籤如 5/9，預設今天"}
            },
            "required": ["meal_time", "food"]
        }
    },
    {
        "name": "save_inbody_record",
        "description": "儲存 InBody 身體數據到 Notion",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "格式 YYYY-MM-DD"},
                "weight": {"type": "number", "description": "體重 kg"},
                "skeletal_muscle": {"type": "number", "description": "骨骼肌重 kg"},
                "body_fat": {"type": "number", "description": "體脂肪重 kg"},
                "body_fat_percent": {"type": "number", "description": "體脂率 %"},
                "visceral_fat": {"type": "number", "description": "內臟脂肪"},
                "bmr": {"type": "number", "description": "基礎代謝 kcal"},
                "bmi": {"type": "number", "description": "BMI"},
                "muscle_mass": {"type": "number", "description": "肌肉量 kg"}
            },
            "required": ["date"]
        }
    }
]

def history_add(chat_id, role, text):
    conv_history[chat_id].append({"role": role, "content": text})
    if len(conv_history[chat_id]) > 10:
        conv_history[chat_id] = conv_history[chat_id][-10:]


def today_label():
    n = datetime.now()
    return f"{n.month}/{n.day}"

def today_iso():
    return datetime.now().strftime("%Y-%m-%d")

def parse_meal(text):
    for kw, name in MEAL_MAP.items():
        if text.startswith(kw):
            return name, text[len(kw):].strip()
    return None, text

def ask_claude(text, image_bytes=None):
    """內部使用（解析、分類），不帶對話歷史。"""
    content = []
    if image_bytes:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.standard_b64encode(image_bytes).decode()},
        })
    content.append({"type": "text", "text": text})
    resp = ai.messages.create(
        model="claude-sonnet-4-6", max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return resp.content[0].text.strip()

def execute_tool(name, params):
    """執行 Claude 要求的工具呼叫，回傳結果字串。"""
    if name == "query_notion":
        db_id = DB_MAP.get(params["database"])
        payload = {"page_size": 5, "sorts": [{"timestamp": "created_time", "direction": "descending"}]}
        if params.get("date"):
            # 先查指定日期，如果沒結果就改查最近 5 筆
            payload["filter"] = {"property": "Date", "date": {"equals": params["date"]}}
            r = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query",
                              headers=NOTION_HEADERS, json=payload, timeout=10)
            if not r.json().get("results"):
                payload.pop("filter")  # 沒結果就改拿最近資料
        r = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query",
                          headers=NOTION_HEADERS, json=payload, timeout=10)
        rows = []
        for item in r.json().get("results", []):
            row = {"page_id": item["id"]}
            for field, prop in item["properties"].items():
                t = prop.get("type")
                if t == "number" and prop.get("number") is not None:
                    row[field] = prop["number"]
                elif t == "date" and prop.get("date"):
                    row[field] = prop["date"]["start"]
                elif t == "title":
                    txts = prop.get("title", [])
                    if txts:
                        row[field] = txts[0].get("plain_text", "")
                elif t == "rich_text":
                    txts = prop.get("rich_text", [])
                    if txts:
                        row[field] = txts[0].get("plain_text", "")
                elif t == "select" and prop.get("select"):
                    row[field] = prop["select"]["name"]
            rows.append(row)
        return json.dumps(rows, ensure_ascii=False)

    elif name == "update_notion_page":
        props = {}
        for field, value in params["fields"].items():
            if isinstance(value, (int, float)):
                props[field] = {"number": value}
            elif isinstance(value, str):
                props[field] = {"rich_text": [{"text": {"content": value}}]}
        r = requests.patch(f"https://api.notion.com/v1/pages/{params['page_id']}",
                           headers=NOTION_HEADERS, json={"properties": props}, timeout=10)
        return "更新成功" if r.status_code == 200 else f"失敗 {r.status_code}"

    elif name == "delete_notion_page":
        r = requests.patch(f"https://api.notion.com/v1/pages/{params['page_id']}",
                           headers=NOTION_HEADERS, json={"archived": True}, timeout=10)
        return "已刪除" if r.status_code == 200 else f"失敗 {r.status_code}"

    elif name == "save_diet_record":
        label = params.get("date_label") or today_label()
        ok = notion_save_diet(label, params["meal_time"], params["food"])
        return "已存入" if ok else "儲存失敗"

    elif name == "save_inbody_record":
        key_map = {
            "weight": "體重", "skeletal_muscle": "骨骼肌重",
            "body_fat": "體脂肪重", "body_fat_percent": "體脂率",
            "visceral_fat": "內臟脂肪", "bmr": "基礎代謝",
            "bmi": "BMI", "muscle_mass": "肌肉量",
        }
        data = {"日期": params.get("date", today_iso())}
        for en, zh in key_map.items():
            if params.get(en) is not None:
                data[zh] = params[en]
        ok = notion_save_inbody(data)
        return "已存入" if ok else "儲存失敗"

    return f"未知工具: {name}"


def ask_claude_chat(chat_id, text, image_bytes=None):
    """Agentic loop：Claude 可自主呼叫 Notion 工具，支援對話歷史。"""
    current = []
    if image_bytes:
        current.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.standard_b64encode(image_bytes).decode()},
        })
    current.append({"type": "text", "text": text})

    messages = list(conv_history[chat_id]) + [{"role": "user", "content": current}]
    final_reply = ""

    for _ in range(8):  # 最多 8 輪工具呼叫，避免無限迴圈
        resp = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # 收集文字
        for block in resp.content:
            if hasattr(block, "text"):
                final_reply = block.text.strip()

        if resp.stop_reason == "end_turn":
            break

        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    history_add(chat_id, "user", f"[圖片] {text}" if image_bytes else text)
    history_add(chat_id, "assistant", final_reply)
    return final_reply

def extract_inbody(image_bytes):
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                      "data": base64.standard_b64encode(image_bytes).decode()}},
        {"type": "text", "text": "這是一張 InBody 身體組成分析報告圖片。請仔細讀取並以 JSON 格式回傳以下數據（找不到的填 null）：{\"日期\": \"YYYY-MM-DD格式，從報告上讀取，找不到填null\", \"體重\": 數字, \"骨骼肌重\": 數字, \"體脂肪重\": 數字, \"體脂率\": 數字, \"內臟脂肪\": 數字, \"基礎代謝\": 數字, \"BMI\": 數字, \"肌肉量\": 數字}。只回傳 JSON，不要其他文字。"}
    ]
    resp = ai.messages.create(
        model="claude-sonnet-4-6", max_tokens=512,
        messages=[{"role": "user", "content": content}],
    )
    text = resp.content[0].text.strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return {}

def notion_save_diet(date_label, meal_time, food):
    payload = {
        "parent": {"database_id": NOTION_DIET_DB},
        "properties": {
            "日期":  {"title":     [{"text": {"content": date_label}}]},
            "時段":  {"select":    {"name": meal_time}},
            "餐點":  {"rich_text": [{"text": {"content": food}}]},
        },
    }
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS, json=payload, timeout=10)
    return r.status_code == 200

def notion_save_inbody(data: dict):
    date_str = data.get("日期") or today_iso()
    # Name 用 Notion date mention 格式，對應既有紀錄的 @YYYY/MM/DD
    props = {
        "Name": {"title": [{"type": "mention", "mention": {"type": "date", "date": {"start": date_str}}}]},
        "Date": {"date": {"start": date_str}},
    }
    field_map = ["體重", "骨骼肌重", "體脂肪重", "體脂率", "內臟脂肪", "基礎代謝", "BMI", "肌肉量"]
    for key in field_map:
        val = data.get(key)
        if val is not None:
            props[key] = {"number": float(val)}
    payload = {"parent": {"database_id": NOTION_INBODY_DB}, "properties": props}
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS, json=payload, timeout=10)
    return r.status_code == 200

def notion_today_diet(date_label):
    payload = {"filter": {"property": "日期", "title": {"contains": date_label}}}
    r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DIET_DB}/query",
                      headers=NOTION_HEADERS, json=payload, timeout=10)
    if r.status_code != 200:
        return []
    out = []
    for item in r.json().get("results", []):
        props = item["properties"]
        sel   = (props.get("時段") or {}).get("select") or {}
        texts = (props.get("餐點") or {}).get("rich_text") or []
        food  = texts[0]["text"]["content"] if texts else ""
        if food:
            out.append({"時段": sel.get("name", ""), "餐點": food})
    return out


# ── Workout helpers ─────────────────────────────────────────

def is_workout_log(text):
    return bool(re.search(r'組\s*\d+\s*:', text)) and bool(re.search(r'\d+\s*kg\s*x\s*\d+', text))

def parse_workout_text(text):
    """Use Claude to parse workout log into structured JSON."""
    prompt = f"""以下是一份訓練日誌，請解析成 JSON：

{text}

回傳格式（只回傳 JSON）：
{{
  "exercises": [
    {{
      "name": "動作名稱",
      "note": "引號內的教練備注，沒有則為 null",
      "sets": [
        {{"weight": 數字, "reps": 數字}},
        ...
      ]
    }},
    ...
  ]
}}"""
    resp = ai.messages.create(
        model="claude-sonnet-4-6", max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    m = re.search(r'\{.*\}', resp.content[0].text, re.DOTALL)
    return json.loads(m.group()) if m else {"exercises": []}

def classify_exercise(name):
    """Use Claude to classify an exercise for the Exercise Library."""
    prompt = f"""健身動作「{name}」的分類，只回傳 JSON：
{{
  "主要訓練部位": ["從以下選：胸肌, 背肌, 肩膀(三角肌), 肱二頭肌, 肱三頭肌, 腹肌, 腿部(股四頭肌), 腿後肌群, 臀肌, 小腿肌群"],
  "使用器材": ["從以下選：啞鈴, 槓鈴, Cable, 史密斯機, 壺鈴, 彈力帶, 自由重量, 固定器械, 徒手"],
  "目標肌群": "從以下選一：推, 拉, 腿, 核心"
}}"""
    resp = ai.messages.create(
        model="claude-sonnet-4-6", max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    m = re.search(r'\{.*\}', resp.content[0].text, re.DOTALL)
    return json.loads(m.group()) if m else {}

def notion_find_exercise(name):
    """Search Exercise Library for existing exercise. Returns page_id or None."""
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_EXLIB_DB}/query",
        headers=NOTION_HEADERS,
        json={"filter": {"property": "動作名稱", "title": {"equals": name}}},
        timeout=10
    )
    results = r.json().get("results", [])
    return results[0]["id"] if results else None

def notion_create_exercise(name, note=None):
    """Create exercise in Exercise Library. Returns page_id."""
    info = classify_exercise(name)
    props = {"動作名稱": {"title": [{"text": {"content": name}}]}}
    if info.get("主要訓練部位"):
        props["主要訓練部位"] = {"multi_select": [{"name": v} for v in info["主要訓練部位"]]}
    if info.get("使用器材"):
        props["使用器材"] = {"multi_select": [{"name": v} for v in info["使用器材"]]}
    if info.get("目標肌群"):
        props["目標肌群"] = {"select": {"name": info["目標肌群"]}}

    payload = {"parent": {"database_id": NOTION_EXLIB_DB}, "properties": props}
    if note:
        payload["children"] = [{
            "object": "block", "type": "callout",
            "callout": {
                "icon": {"type": "emoji", "emoji": "💡"},
                "rich_text": [{"type": "text", "text": {"content": f"教練備注：{note}"}}]
            }
        }]
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS, json=payload, timeout=10)
    return r.json().get("id")

def notion_create_set_log(exercise_id, date_str, sets, exercise_name):
    """Create Set Log entry. Returns page_id."""
    props = {
        "Name": {"title": [{"text": {"content": exercise_name}}]},
        "日期": {"date": {"start": date_str}},
    }
    if exercise_id:
        props["動作"] = {"relation": [{"id": exercise_id}]}
    for i, s in enumerate(sets[:6], 1):
        props[f"組{i}重"] = {"number": s.get("weight")}
        props[f"組{i}次"] = {"number": s.get("reps")}
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS,
                      json={"parent": {"database_id": NOTION_SETLOG_DB}, "properties": props},
                      timeout=10)
    return r.json().get("id")

def notion_get_exercise_muscles(exercise_id):
    """取得動作資料庫中某動作的主要訓練部位。"""
    r = requests.get(f"https://api.notion.com/v1/pages/{exercise_id}",
                     headers=NOTION_HEADERS, timeout=10)
    if r.status_code != 200:
        return []
    return [m["name"] for m in r.json()["properties"]
            .get("主要訓練部位", {}).get("multi_select", [])]

def notion_get_muscles_from_setlogs(set_log_ids):
    """從多筆 Set Log 收集不重複的肌群名稱。"""
    muscles = []
    for sid in set_log_ids:
        r = requests.get(f"https://api.notion.com/v1/pages/{sid}",
                         headers=NOTION_HEADERS, timeout=10)
        if r.status_code != 200:
            continue
        ex_rel = r.json()["properties"].get("動作", {}).get("relation", [])
        for ex in ex_rel:
            for m in notion_get_exercise_muscles(ex["id"]):
                if m not in muscles:
                    muscles.append(m)
    return muscles

def notion_create_workout_log(date_str, set_log_ids):
    """Create Workout Log entry，並自動填入訓練部位。"""
    muscles = notion_get_muscles_from_setlogs(set_log_ids)
    props = {
        "Name": {"title": [{"text": {"content": date_str}}]},
        "Date": {"date": {"start": date_str}},
    }
    if set_log_ids:
        props["單組紀錄 ( Set Log )"] = {"relation": [{"id": i} for i in set_log_ids if i]}
    if muscles:
        props["訓練部位"] = {"multi_select": [{"name": m} for m in muscles]}
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS,
                      json={"parent": {"database_id": NOTION_WORKOUT_DB}, "properties": props},
                      timeout=10)
    return r.status_code == 200, muscles

def save_workout_to_notion(exercises):
    """Full pipeline: parse exercises → create/find in Library → create Set Logs → create Workout Log."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    set_log_ids = []
    results = []

    for ex in exercises:
        name = ex["name"]
        note = ex.get("note")
        sets = ex.get("sets", [])

        # Find or create in Exercise Library
        ex_id = notion_find_exercise(name)
        is_new = ex_id is None
        if is_new:
            ex_id = notion_create_exercise(name, note)

        # Create Set Log
        sl_id = notion_create_set_log(ex_id, date_str, sets, name)
        if sl_id:
            set_log_ids.append(sl_id)

        results.append({"name": name, "new": is_new, "sets": len(sets)})

    # Create Workout Log（含訓練部位）
    ok, muscles = notion_create_workout_log(date_str, set_log_ids)
    return results, muscles


@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.reply_to(message,
        "👋 嗨！我是豪猛教練 💪\n\n"
        "你可以問我任何健身問題\n"
        "傳食物照片 → 分析營養\n"
        "傳 InBody 照片 → 自動存入 Notion\n\n"
        "記錄飲食：早餐 燕麥雞蛋\n\n"
        "/today → 今日飲食紀錄\n"
        "/goal  → 碳循環目標"
    )

@bot.message_handler(commands=["today"])
def cmd_today(message):
    label = today_label()
    records = notion_today_diet(label)
    if not records:
        bot.reply_to(message, f"📋 {label} 今日尚無飲食紀錄")
        return
    lines = [f"📋 {label} 今日飲食：\n"]
    for r in records:
        emoji = MEAL_EMOJI.get(r["時段"], "🍽")
        lines.append(f"{emoji} {r['時段']}：{r['餐點']}")
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=["goal"])
def cmd_goal(message):
    bot.reply_to(message,
        "🎯 碳循環目標（六月正式啟動）\n\n"
        "🔴 低碳日：碳水100g｜蛋白質240g｜脂肪100g = 2260kcal\n"
        "🟡 中碳日：碳水250g｜蛋白質200g｜脂肪60g  = 2340kcal\n"
        "🟢 高碳日：碳水400g｜蛋白質160g｜脂肪30g  = 2510kcal\n\n"
        "📅 五月碳循環暫停，六月正式啟動！"
    )

@bot.message_handler(commands=["report"])
def cmd_report(message):
    text = message.text.replace("/report", "").strip()
    if not text:
        bot.reply_to(message,
            "請在指令後面加上今天的回報，例如：\n"
            "/report 今天練了背，引體向上10下5組，吃了雞胸飯，水喝了3000cc，感覺不錯"
        )
        return

    bot.send_chat_action(message.chat.id, "typing")

    # Claude 解析回報內容
    parse_prompt = f"""學員晚間回報：「{text}」

請以 JSON 格式解析（找不到的填 null 或 false）：
{{
  "有訓練": true或false,
  "訓練摘要": "訓練內容簡述",
  "飲食摘要": "飲食內容簡述",
  "水達標": true或false,
  "整體評估": "一句話評估今天表現"
}}
只回傳 JSON。"""

    resp = ai.messages.create(
        model="claude-sonnet-4-6", max_tokens=300,
        messages=[{"role": "user", "content": parse_prompt}]
    )
    raw = resp.content[0].text.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    data = json.loads(match.group()) if match else {}

    # 存入 Notion 每日習慣追蹤
    today = datetime.now().strftime("%Y-%m-%d")
    note = f"訓練：{data.get('訓練摘要') or '無'} | 飲食：{data.get('飲食摘要') or '無'} | 原文：{text}"
    props = {
        "Name": {"title": [{"type": "mention", "mention": {"type": "date", "date": {"start": today}}}]},
        "Date": {"date": {"start": today}},
        "學習進度": {"rich_text": [{"text": {"content": note[:500]}}]},
        "喝水2000CC": {"checkbox": bool(data.get("水達標"))},
        "每日學習": {"checkbox": False},
    }
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS,
                      json={"parent": {"database_id": NOTION_HABITS_DB}, "properties": props},
                      timeout=10)
    notion_ok = r.status_code == 200

    # Claude 給回饋
    feedback_prompt = f"學員今日回報：「{text}」\n\n根據這份回報給一段簡短的今日評估和明天建議，語氣正面鼓勵，加上 emoji，不超過 150 字。"
    feedback = ask_claude_chat(message.chat.id, feedback_prompt)

    tag = "✅ 已記錄到 Notion" if notion_ok else "⚠️ Notion 儲存失敗"
    bot.reply_to(message, f"{tag}\n\n{feedback}")


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    bot.send_chat_action(message.chat.id, "typing")
    file_info   = bot.get_file(message.photo[-1].file_id)
    image_bytes = bot.download_file(file_info.file_path)
    caption     = (message.caption or "").lower()

    is_inbody = any(kw in caption for kw in ["inbody", "身材", "體重", "量測", "體脂"])

    if not is_inbody:
        detect = ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=10,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                              "data": base64.standard_b64encode(image_bytes).decode()}},
                {"type": "text", "text": "這是 InBody 身體組成報告嗎？只回答 yes 或 no。"}
            ]}]
        )
        is_inbody = "yes" in detect.content[0].text.lower()

    if is_inbody:
        bot.reply_to(message, "📊 偵測到 InBody 報告，解析中...")
        data = extract_inbody(image_bytes)
        if not data:
            bot.reply_to(message, "⚠️ 無法解析數據，請確認圖片清晰")
            return
        ok = notion_save_inbody(data)
        lines = ["✅ InBody 已存入 Notion！\n" if ok else "⚠️ Notion 儲存失敗\n"]
        for k in ["體重", "骨骼肌重", "體脂肪重", "體脂率", "內臟脂肪", "基礎代謝", "BMI", "肌肉量"]:
            v = data.get(k)
            if v is not None:
                lines.append(f"  {k}：{v}")
        reply_text = "\n".join(lines)
        bot.reply_to(message, reply_text)
        # 更新歷史
        summary = ", ".join(f"{k}:{data[k]}" for k in ["體重","體脂率","骨骼肌重"] if data.get(k))
        history_add(message.chat.id, "user", f"[InBody圖片] {summary}")
        history_add(message.chat.id, "assistant", reply_text)
    else:
        caption_text = message.caption or "請分析這張食物照片，估算蛋白質、碳水、脂肪和總熱量。"
        reply = ask_claude_chat(message.chat.id, caption_text, image_bytes=image_bytes)
        bot.reply_to(message, reply)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    text = message.text.strip()
    chat_id = message.chat.id
    bot.send_chat_action(chat_id, "typing")

    if is_workout_log(text):
        bot.reply_to(message, "🏋️ 偵測到訓練記錄，存入 Notion 中...")
        data = parse_workout_text(text)
        exercises = data.get("exercises", [])
        if not exercises:
            bot.reply_to(message, "⚠️ 無法解析訓練內容，請確認格式")
            return
        results, muscles = save_workout_to_notion(exercises)
        lines = ["✅ 訓練已存入 Notion！\n"]
        for r in results:
            tag = "🆕 新增動作" if r["new"] else "✔ 已有動作"
            lines.append(f"{tag}｜{r['name']}（{r['sets']} 組）")
        if muscles:
            lines.append(f"\n💪 訓練部位：{' / '.join(muscles)}")
        reply_text = "\n".join(lines)
        bot.reply_to(message, reply_text)
        history_add(chat_id, "user", f"[訓練記錄] {', '.join(r['name'] for r in results)}")
        history_add(chat_id, "assistant", reply_text)
        return

    meal_time, food = parse_meal(text)
    if meal_time and food:
        prompt = f"學員記錄了{meal_time}：{food}，請估算這餐的蛋白質、碳水、脂肪和總熱量，並簡短評估是否符合健體訓練目標。"
        reply  = ask_claude_chat(chat_id, prompt)
        ok     = notion_save_diet(today_label(), meal_time, food)
        emoji  = MEAL_EMOJI.get(meal_time, "🍽")
        tag    = "✅ 已存入 Notion" if ok else "⚠️ Notion 儲存失敗"
        bot.reply_to(message, f"{emoji} {meal_time}：{food}\n{tag}\n\n{reply}")
    else:
        reply = ask_claude_chat(chat_id, text)
        bot.reply_to(message, reply)

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    print("Bot started.")
    bot.infinity_polling()
