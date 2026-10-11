"""Descobre o seu chat id do Telegram. Antes: crie o bot no @BotFather e mande /start para ele.

Uso: TELEGRAM_TOKEN=123:ABC python scripts/telegram_chat_id.py
"""
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
data = requests.get(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/getUpdates", timeout=30).json()
chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "") for u in data.get("result", [])
         if "message" in u}
print(chats or "Nenhuma mensagem ainda: mande /start para o seu bot e rode de novo.")
