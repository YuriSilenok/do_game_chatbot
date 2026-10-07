import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

SERVER_URL = "http://127.0.0.1:8000"


def send_message(url: str, name: str, text: str) -> None:
    payload = json.dumps({"sender": name, "text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Сервер вернул HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Не удалось подключиться к серверу: {error.reason}") from error


def main() -> None:
    room = input("Комната: ").strip()
    name = input("Имя: ").strip()
    if not room or not name:
        print("Нужно указать номер комнаты и имя.", file=sys.stderr)
        return
    url = f"{SERVER_URL.rstrip('/')}/api/rooms/{quote(room, safe='')}/messages"

    try:
        while True:
            text = input()
            if text.strip():
                send_message(url, name, text)
    except (EOFError, KeyboardInterrupt):
        return
    except RuntimeError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except (EOFError, KeyboardInterrupt):
        return


if __name__ == "__main__":
    main()