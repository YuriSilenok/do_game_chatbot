# bot.py
"""
Отдельный ИИ-бот для танковой игры.

Алгоритм:
  1. Найти ближайшего противника.
  2. Если маршрут до ближайшего противника есть:
       - есть прямая видимость  -> стрелять в противника;
       - нет прямой видимости   -> двигаться к противнику.
  3. Если маршрута до ближайшего противника нет:
       - найти ближайшую стену;
       - есть маршрут до стены и прямая видимость -> стрелять в стену;
       - есть маршрут до стены, но нет видимости  -> двигаться к стене.

Пока до противника есть маршрут — бот НИКОГДА не переключается на стену.
"""

import asyncio
import time
from collections import deque

import aiohttp


BASE_URL = "http://127.0.0.1:8080"
ROOM_ID = "1"
BOT_NAME = "Бот-Разведчик"
POLL_INTERVAL = 0.15
COMMAND_COOLDOWN = 0.20


DIRECTIONS = {
    "вверх": (0, -1),
    "вниз": (0, 1),
    "влево": (-1, 0),
    "вправо": (1, 0),
}

BLOCKING_TILES = {1, 2, 4, 6}      # кирпич, сталь, вода, бетон
PASSABLE_TILES = {0, 3, 5}         # пусто, лёд, трава
BRICK_TILE = 1


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def tile_at(tiles, x, y):
    if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]):
        return tiles[y][x]
    return None


def line_of_sight(tiles, first, second):
    """Проверяет, что между двумя клетками нет блокирующих тайлов."""
    x1, y1 = first
    x2, y2 = second
    x_start, y_start = x1 + 0.5, y1 + 0.5
    x_end, y_end = x2 + 0.5, y2 + 0.5
    samples = max(abs(x2 - x1), abs(y2 - y1)) * 20
    if samples == 0:
        return True
    for step in range(1, int(samples)):
        x = int(x_start + (x_end - x_start) * step / samples)
        y = int(y_start + (y_end - y_start) * step / samples)
        if tile_at(tiles, x, y) in BLOCKING_TILES:
            return False
    return True


def direction_between(src, dst):
    """Возвращает направление, если клетки стоят на одной линии."""
    dx = dst[0] - src[0]
    dy = dst[1] - src[1]
    if dx == 0 and dy != 0:
        return "вниз" if dy > 0 else "вверх"
    if dy == 0 and dx != 0:
        return "вправо" if dx > 0 else "влево"
    return None


def shoot_direction(tiles, src, dst):
    """Направление выстрела, если цель видна и на одной линии, иначе None."""
    if not line_of_sight(tiles, src, dst):
        return None
    return direction_between(src, dst)


def bfs_next_step(tiles, start, goals, blocked):
    """
    Ищет кратчайший путь от start до любой клетки из goals.
    Возвращает первое направление шага или None, если пути нет.
    """
    if start in goals:
        return None

    height = len(tiles)
    width = len(tiles[0])
    queue = deque([(start, None)])
    visited = {start}

    while queue:
        (x, y), first_dir = queue.popleft()
        for name, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in visited or (nx, ny) in blocked:
                continue
            if tiles[ny][nx] not in PASSABLE_TILES:
                continue
            if (nx, ny) in goals:
                return first_dir or name
            visited.add((nx, ny))
            queue.append(((nx, ny), first_dir or name))
    return None


def nearest_enemy(me, enemies):
    """Ближайший противник по евклидову расстоянию."""
    if not enemies:
        return None
    mx, my = me["x"], me["y"]
    return min(enemies, key=lambda e: (e["x"] - mx) ** 2 + (e["y"] - my) ** 2)


def nearest_brick(tiles, start):
    """Ближайший кирпич по манхэттенскому расстоянию."""
    height = len(tiles)
    width = len(tiles[0])
    best = None
    best_dist = None
    for y in range(height):
        for x in range(width):
            if tiles[y][x] == BRICK_TILE:
                dist = abs(x - start[0]) + abs(y - start[1])
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = (x, y)
    return best


def cells_next_to(target_cell, tiles, blocked, exclude=None):
    """Проходимые клетки, соседние с target_cell."""
    result = set()
    for _, (dx, dy) in DIRECTIONS.items():
        cell = (target_cell[0] + dx, target_cell[1] + dy)
        if exclude is not None and cell == exclude:
            continue
        if tile_at(tiles, *cell) in PASSABLE_TILES and cell not in blocked:
            result.add(cell)
    return result


def cells_on_line_with(target_cell, tiles, blocked, exclude=None, radius=12):
    """
    Проходимые клетки, с которых target_cell виден по одной из осей
    (на одной линии и без блоков между).
    """
    result = set()
    tx, ty = target_cell
    for _, (dx, dy) in DIRECTIONS.items():
        x, y = tx + dx, ty + dy
        for _ in range(radius):
            if tile_at(tiles, x, y) is None:
                break
            tile = tiles[y][x]
            if tile in BLOCKING_TILES:
                break
            if tile in PASSABLE_TILES and (x, y) not in blocked:
                if exclude is None or (x, y) != exclude:
                    result.add((x, y))
            x += dx
            y += dy
    return result


def path_to_any_goal(tiles, start, goals, blocked):
    """
    Возвращает (has_path, step):
      has_path — есть ли путь до goals (или start уже в goals);
      step     — первое направление шага или None, если шаг не нужен.
    """
    if not goals:
        return False, None
    if start in goals:
        return True, None
    step = bfs_next_step(tiles, start, goals, blocked - {start})
    if step is None:
        return False, None
    return True, step


# ---------------------------------------------------------------------------
# Клиент игры
# ---------------------------------------------------------------------------
class BotClient:
    def __init__(self, base_url, room_id, name):
        self.base_url = base_url.rstrip("/")
        self.room_id = room_id
        self.name = name
        self.session = None
        self.last_command_at = 0.0
        self.color = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc_info):
        if self.session:
            await self.session.close()

    # -- HTTP-обёртки ------------------------------------------------------
    async def get_state(self):
        async with self.session.get(
            f"{self.base_url}/rooms/{self.room_id}/state"
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def send_message(self, text):
        payload = {"sender": self.name, "text": text}
        async with self.session.post(
            f"{self.base_url}/rooms/{self.room_id}/messages", json=payload
        ) as resp:
            resp.raise_for_status()

    async def join(self):
        payload = {"name": self.name}
        async with self.session.post(
            f"{self.base_url}/rooms/{self.room_id}/join", json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self.color = data.get("your_color")

    # -- Логика бота -------------------------------------------------------
    def find_me(self, state):
        for tank in state.get("tanks", []):
            if tank.get("name") == self.name and tank.get("alive"):
                return tank
        return None

    def find_enemies(self, state):
        return [
            t for t in state.get("tanks", [])
            if t.get("alive") and t.get("name") != self.name
        ]

    def turn_or_shoot(self, my_dir, target_cell, tiles, my_cell):
        """
        Если цель на линии и видна — развернуться к ней и выстрелить.
        Возвращает команду или None.
        """
        shoot_dir = shoot_direction(tiles, my_cell, target_cell)
        if shoot_dir is None:
            return None
        if my_dir != shoot_dir:
            return shoot_dir
        return "выстрел"

    def choose_command(self, state):
        me = self.find_me(state)
        if me is None:
            return None

        tiles = state["map"]["tiles"]
        blocked_all = {
            (int(t["x"]), int(t["y"]))
            for t in state.get("tanks", [])
            if t.get("alive")
        }
        my_cell = (int(me["x"]), int(me["y"]))
        my_dir = me["direction"]
        # Себя не считаем препятствием для BFS.
        blocked = blocked_all - {my_cell}

        # ----- 1. Ближайший противник ------------------------------------
        enemy = nearest_enemy(me, self.find_enemies(state))
        if enemy is not None:
            enemy_cell = (int(enemy["x"]), int(enemy["y"]))

            enemy_goals = (
                cells_next_to(enemy_cell, tiles, blocked, exclude=my_cell)
                | cells_on_line_with(enemy_cell, tiles, blocked, exclude=my_cell)
            )
            has_path, step = path_to_any_goal(
                tiles, my_cell, enemy_goals, blocked
            )

            if has_path:
                # 1a. Можем стрелять прямо сейчас?
                command = self.turn_or_shoot(
                    my_dir, enemy_cell, tiles, my_cell
                )
                if command is not None:
                    return command

                # 1b. Стрелять нельзя, но можно двигаться.
                if step is not None:
                    return step

                # step is None -> мы уже в goals, но стрелять не можем
                # (например, враг по диагонали). Делаем шаг в сторону,
                # чтобы встать на линию.
                side_goals = cells_on_line_with(
                    enemy_cell, tiles, blocked, exclude=my_cell
                )
                if side_goals:
                    side_step = bfs_next_step(
                        tiles, my_cell, side_goals, blocked
                    )
                    if side_step is not None:
                        return side_step

                # До противника путь формально есть — на стену
                # не переключаемся.
                return None

        # ----- 2. Ближайшая стена ----------------------------------------
        brick = nearest_brick(tiles, my_cell)
        if brick is None:
            return None

        brick_goals = (
            cells_next_to(brick, tiles, blocked, exclude=my_cell)
            | cells_on_line_with(brick, tiles, blocked, exclude=my_cell)
        )
        has_path, step = path_to_any_goal(
            tiles, my_cell, brick_goals, blocked
        )
        if not has_path:
            return None

        # 2a. Можем стрелять в стену?
        command = self.turn_or_shoot(my_dir, brick, tiles, my_cell)
        if command is not None:
            return command

        # 2b. Стрелять нельзя — двигаемся к стене.
        if step is not None:
            return step

        # Уже в goals, но не на линии с кирпичом — шаг в сторону.
        side_goals = cells_on_line_with(brick, tiles, blocked, exclude=my_cell)
        if side_goals:
            side_step = bfs_next_step(tiles, my_cell, side_goals, blocked)
            if side_step is not None:
                return side_step
        return None

    async def tick(self):
        now = time.monotonic()
        if now - self.last_command_at < COMMAND_COOLDOWN:
            return
        try:
            state = await self.get_state()
        except Exception as exc:
            print(f"[bot] Не удалось получить состояние: {exc}")
            return
        if state.get("status") != "round":
            return
        command = self.choose_command(state)
        if not command:
            return
        try:
            await self.send_message(command)
            self.last_command_at = now
        except Exception as exc:
            print(f"[bot] Не удалось отправить команду: {exc}")

    async def run(self):
        print(f"[bot] Запуск. Комната {self.room_id}, имя {self.name}")
        try:
            await self.join()
            print(f"[bot] Зарегистрирован. Цвет: {self.color}")
        except Exception as exc:
            print(f"[bot] Ошибка регистрации: {exc}")
            return
        while True:
            await self.tick()
            await asyncio.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
async def main():
    async with BotClient(BASE_URL, ROOM_ID, BOT_NAME) as bot:
        await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[bot] Остановлен.")