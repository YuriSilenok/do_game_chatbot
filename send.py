# send.py
# Этот файл отвечает только за отправку сообщений на сервер.
# Он ничего не знает про консоль и не спрашивает пользователя —
# просто получает (room_id, name, text) и отправляет POST-запрос.

import json
import urllib.request
from urllib.parse import quote

SERVER_URL = "http://127.0.0.1:8000"


def send_message(room_id, name, text):
    """Отправляет сообщение text в комнату room_id от имени name.

    Ничего не возвращает и ничего не печатает при успехе.
    При ошибке печатает краткое сообщение.
    """
    url = f"{SERVER_URL}/api/rooms/{quote(room_id, safe='')}/messages"

    data = json.dumps({"sender": name, "text": text}, ensure_ascii=False).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        # Читаем и отбрасываем ответ — он больше не нужен.
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
    except Exception as e:
        print(f"Ошибка: {e}")