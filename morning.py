"""每天早上 9 點執行：讀 Notion 數據，發送今日計畫到 Telegram"""
import base64
import os
from datetime import datetime
from dotenv import load_dotenv
import requests
import anthropic
import httpx

load_dotenv()

ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]
BOT_TOKEN     = os.environ["BOT_TOKEN"]
CHAT_ID       = int(os.environ["TELEGRAM_CHAT_ID"])
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_INBODY_DB  = "3f9cf4f23f254b23b702c5d8bb19b016"
NOTION_DIET_DB    = "30e0ef30240a804995f3d8154d4aec90"
NOTION_WORKOUT_DB = "30a0ef30240a8023a4c7f55dafbdd588"
NOTION_SETLOG_DB  = "30a0ef30240a80739a41f3e3b83aab8b"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

ai = anthropic.Anthropic(api_key=ANTHROPIC_KEY, http_client=httpx.Client(verify=False))

WEEKDAY_MAP = {0:"一", 1:"二", 2:"三", 3:"四", 4:"五", 5:"六", 6:"日"}

# 每週訓練計畫（依照 2026 五月計畫）
WORKOUT_DAYS = {0: True, 2: True, 3: True, 6: True}  # 週一、三、四、日

def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10, verify=False
    )

def get_latest_inbody():
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_INBODY_DB}/query",
        headers=NOTION_HEADERS,
        json={"sorts": [{"property": "Date", "direction": "descending"}], "page_size": 2},
        timeout=10
    )
    results = r.json().get("results", [])
    records = []
    for item in results:
        props = item["properties"]
        record = {}
        for field in ["體重", "體脂率", "骨骼肌重", "體脂肪重", "肌肉量", "內臟脂肪", "BMI", "基礎代謝"]:
            val = (props.get(field) or {}).get("number")
            if val is not None:
                record[field] = val
        date_val = (props.get("Date") or {}).get("date") or {}
        record["日期"] = date_val.get("start", "")
        records.append(record)
    return records

def get_latest_workout():
    """取得最近一次訓練紀錄（日期 + 訓練部位 + 動作清單）。"""
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_WORKOUT_DB}/query",
        headers=NOTION_HEADERS,
        json={"sorts": [{"timestamp": "created_time", "direction": "descending"}], "page_size": 1},
        timeout=10
    )
    results = r.json().get("results", [])
    if not results:
        return None
    item = results[0]
    props = item["properties"]
    date_val = (props.get("Date") or {}).get("date") or {}
    date = date_val.get("start", "")
    muscles = [m["name"] for m in (props.get("訓練部位") or {}).get("multi_select", [])]
    # 取 Set Log 的動作名稱
    set_ids = [(s["id"]) for s in (props.get("單組紀錄 ( Set Log )") or {}).get("relation", [])]
    exercises = []
    for sid in set_ids[:8]:
        sr = requests.get(f"https://api.notion.com/v1/pages/{sid}", headers=NOTION_HEADERS, timeout=10)
        if sr.status_code == 200:
            title = sr.json()["properties"].get("Name", {}).get("title", [{}])
            name = title[0].get("plain_text", "") if title else ""
            if name and name not in exercises:
                exercises.append(name)
    return {"date": date, "muscles": muscles, "exercises": exercises}


def get_recent_diet(days=3):
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DIET_DB}/query",
        headers=NOTION_HEADERS,
        json={"sorts": [{"property": "日期", "direction": "descending"}], "page_size": 10},
        timeout=10
    )
    results = r.json().get("results", [])
    records = []
    for item in results:
        props = item["properties"]
        titles = (props.get("日期") or {}).get("title") or []
        date = titles[0]["plain_text"] if titles else ""
        meal = (props.get("時段") or {}).get("select") or {}
        texts = (props.get("餐點") or {}).get("rich_text") or []
        food = texts[0]["text"]["content"] if texts else ""
        if food:
            records.append(f"{date} {meal.get('name','')}：{food}")
    return records[:8]

def main():
    now = datetime.now()
    weekday = now.weekday()
    day_name = WEEKDAY_MAP[weekday]
    is_workout = WORKOUT_DAYS.get(weekday, False)
    date_str = f"{now.month}/{now.day}"

    inbody_records = get_latest_inbody()
    diet_records = get_recent_diet()
    latest_workout = get_latest_workout()

    inbody_text = ""
    if inbody_records:
        latest = inbody_records[0]
        inbody_text = f"最新InBody ({latest.get('日期','')})：體重{latest.get('體重','-')}kg、體脂率{latest.get('體脂率','-')}%、骨骼肌重{latest.get('骨骼肌重','-')}kg"
        if len(inbody_records) > 1:
            prev = inbody_records[1]
            diff_weight = round(latest.get("體重", 0) - prev.get("體重", 0), 1)
            diff_fat = round(latest.get("體脂率", 0) - prev.get("體脂率", 0), 1)
            inbody_text += f"\n上次比較：體重{'+' if diff_weight>=0 else ''}{diff_weight}kg、體脂率{'+' if diff_fat>=0 else ''}{diff_fat}%"

    diet_text = "\n".join(diet_records) if diet_records else "近期無飲食記錄"

    workout_text = "無訓練紀錄"
    if latest_workout:
        w = latest_workout
        workout_text = (f"最近一次訓練（{w['date']}）\n"
                        f"訓練部位：{', '.join(w['muscles']) or '未記錄'}\n"
                        f"動作：{', '.join(w['exercises']) or '未記錄'}")

    prompt = f"""今天是 2026/{date_str}（週{day_name}），{'今天是訓練日 💪' if is_workout else '今天是休息日'}。

學員數據：
{inbody_text}

最近訓練紀錄：
{workout_text}

近期飲食記錄：
{diet_text}

碳循環計畫（六月啟動，目前五月暫停）：
- 低碳日：碳水100g、蛋白質240g = 2260kcal
- 中碳日：碳水250g、蛋白質200g = 2340kcal
- 高碳日：碳水400g、蛋白質160g = 2510kcal

請以「阿布拉教練」身份，用繁體中文寫一份早安日報，包含：
1. 今天日期和星期
2. 今日目標（訓練/休息）
3. 根據最新 InBody 數據的簡短進度評估（有數據才說）
4. 今日飲食建議（蛋白質、水分提醒）
5. 今日一句激勵話
格式簡潔，適合在 Telegram 閱讀，使用 emoji，不要太長。
包含：今日計畫、最近訓練簡評（上次練了什麼部位，今天是否需要換部位）、飲食提醒。"""

    resp = ai.messages.create(
        model="claude-sonnet-4-6", max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    message = resp.content[0].text.strip()
    send_telegram(message)
    print("Morning message sent.")

if __name__ == "__main__":
    main()
