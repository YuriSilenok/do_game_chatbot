import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

SERVER_URL = "http://127.0.0.1:8000"


def send_message(room_id: str, name: str, text: str) -> None:
    """Отправить сообщение в комнату room_id от имени name."""
    url = f"{SERVER_URL.rstrip('/')}/api/rooms/{quote(room_id, safe='')}/messages"
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


def parse_join(text: str):
    """Если текст — команда вида «войти НОМЕР [ИМЯ]», вернуть (номер, имя_из_команды).

    Возвращает (room_id, join_name) или (None, None), если это не вход в комнату.
    """
    parts = text.split(maxsplit=2)
    if len(parts) >= 2 and parts[0].casefold() == "войти":
        return parts[1], (parts[2] if len(parts) == 3 else None)
    return None, None


def main() -> None:
    name = input("Имя: ").strip()
    if not name:
        print("Нужно указать имя.", file=sys.stderr)
        return

    room_id: str | None = None
    print("Введите «войти НОМЕР_КОМНАТЫ», чтобы войти в комнату, затем — команды (вверх/вниз/влево/вправо/выстрел) или сообщения.", file=sys.stderr)

    try:
        while True:
            text = input()
            if not text.strip():
                continue
            join_room, join_name = parse_join(text)
            if join_room is not None:
                room_id = join_room
                # Сервер ждёт команду «войти НОМЕР ИМЯ» — добавим своё имя,
                # если пользователь не указал его в команде.
                if join_name is None:
                    text = f"войти {room_id} {name}"
                else:
                    # Если имя в команде задано явно, используем именно его.
                    name = join_name
            if room_id is None:
                print("Сначала войдите в комнату командой «войти НОМЕР».", file=sys.stderr)
                continue
            try:
                send_message(room_id, name, text)
            except RuntimeError as error:
                print(f"Ошибка: {error}", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        return


if __name__ == "__main__":
    main()