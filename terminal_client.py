import argparse
import json
import urllib.error
import urllib.request


def post_message(server: str, room: str, sender: str, text: str) -> None:
    payload = json.dumps({"sender": sender, "text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{server.rstrip('/')}/api/rooms/{room}/messages",
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
    parser = argparse.ArgumentParser(description="Отправка сообщений и команд в танковый чат")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="Адрес сервера")
    parser.add_argument("--room", required=True, help="Номер комнаты")
    parser.add_argument("--name", required=True, help="Имя в чате")
    args = parser.parse_args()

    try:
        while True:
            text = input()
            if text.strip():
                post_message(args.server, args.room, args.name, text)
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
