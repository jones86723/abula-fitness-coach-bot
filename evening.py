"""每天晚上 10 點執行：發送晚間回顧問題到 Telegram"""
import os
from datetime import datetime
from dotenv import load_dotenv
import requests

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = int(os.environ["TELEGRAM_CHAT_ID"])

WEEKDAY_MAP = {0:"一", 1:"二", 2:"三", 3:"四", 4:"五", 5:"六", 6:"日"}
WORKOUT_DAYS = {0: True, 2: True, 3: True, 6: True}

def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=10, verify=False
    )

def main():
    now = datetime.now()
    weekday = now.weekday()
    day_name = WEEKDAY_MAP[weekday]
    is_workout = WORKOUT_DAYS.get(weekday, False)
    date_str = f"{now.month}/{now.day}"

    if is_workout:
        msg = (
            f"🌙 {date_str}（週{day_name}）晚間回顧\n\n"
            "今天訓練日，來回報一下：\n\n"
            "請直接傳給我：\n"
            "1️⃣ 今天練了什麼部位？重量/次數如何？\n"
            "2️⃣ 今天飲食有記錄嗎？蛋白質有達標嗎？\n"
            "3️⃣ 水喝夠 3000cc 了嗎？\n"
            "4️⃣ 今天身體感覺如何？\n\n"
            "用 /report 開頭回覆我，例如：\n"
            "/report 今天練了背，引體向上10下5組，吃了雞胸飯，水喝了3000cc"
        )
    else:
        msg = (
            f"🌙 {date_str}（週{day_name}）晚間回顧\n\n"
            "今天是休息日，來回報一下：\n\n"
            "1️⃣ 今天飲食吃了什麼？\n"
            "2️⃣ 水喝夠 3000cc 了嗎？\n"
            "3️⃣ 今天有做到哪些健康習慣？\n\n"
            "用 /report 開頭回覆我，例如：\n"
            "/report 今天吃了雞胸飯，水喝了2500cc，有做伸展"
        )
    send_telegram(msg)
    print("Evening message sent.")

if __name__ == "__main__":
    main()
