from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from game import STATE_LONGPOLL_SECONDS, game


BASE_DIR = Path(__file__).resolve().parent
state_condition = asyncio.Condition()
# Сериализует вызовы process_room_events, чтобы тик не выполнялся
# параллельно из /api/state и room_event_loop.
_state_lock = asyncio.Lock()
room_wakeup = asyncio.Event()
room_task: Optional[asyncio.Task] = None


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class CommandRequest(BaseModel):
    sender: str = Field(min_length=1, max_length=40)
    command: str = Field(min_length=1, max_length=20)


app = FastAPI(title="Танковый чат")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _bump_version() -> None:
    """Увеличивает версию состояния — вызывается под глобальным локом."""
    game.room.state_version += 1


async def publish_room_event() -> None:
    """
    Публикует событие: увеличивает версию и будит long-poll'ы.
    Лок держим минимально — только на bump + notify, чтобы не
    блокировать другие корутины.
    """
    global room_task
    async with state_condition:
        _bump_version()
        if room_task is None or room_task.done():
            room_task = asyncio.create_task(room_event_loop())
        room_wakeup.set()
        state_condition.notify_all()


async def _run_tick() -> None:
    """
    Выполняет один тик симуляции ВНЕ state_condition.
    Тик может быть долгим (много снарядов, BFS ботов), но он больше
    не блокирует long-poll'ы. По завершении увеличивает версию и
    будит ожидающих.
    """
    async with _state_lock:
        try:
            await game.process_room_events(game.room)
        except Exception as exc:  # не даём тику убить event loop
            print(f"[tick] error: {exc!r}")
    async with state_condition:
        _bump_version()
        state_condition.notify_all()


async def room_event_loop() -> None:
    while True:
        room_wakeup.clear()
        delay = game.next_room_event_delay(game.room)
        try:
            if delay is None:
                await room_wakeup.wait()
            else:
                await asyncio.wait_for(room_wakeup.wait(), timeout=max(delay, 0.001))
        except asyncio.TimeoutError:
            await _run_tick()


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/join")
async def join_room(payload: JoinRequest):
    room = game.room
    try:
        game.join(room, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await publish_room_event()

    tank = next(
        (t for t in room.tanks
         if not t.is_bot and t.name.casefold() == payload.name.strip().casefold()),
        None,
    )
    return {
        **game.room_summary(room),
        "your_color": tank.color if tank else None,
        "your_tank_id": tank.id if tank else None,
    }


@app.post("/api/commands", status_code=status.HTTP_201_CREATED)
async def send_command(payload: CommandRequest):
    room = game.room
    normalized = payload.command.strip().casefold()
    if normalized not in {"вверх", "вниз", "влево", "вправо", "выстрел"}:
        raise HTTPException(status_code=422, detail="Неизвестная команда.")

    sender = payload.sender.strip().casefold()
    tank = next(
        (t for t in room.tanks if t.alive and t.name.casefold() == sender),
        None,
    )
    if tank is None:
        raise HTTPException(status_code=409, detail="Танк не найден или уничтожен.")

    # «Пробуждаем» игрока, даже если он стал ботом по простою.
    tank.is_bot = False
    tank.last_command_at = time.monotonic()
    tank.next_bot_command_at = 0
    game.apply_command(room, tank, normalized)

    await publish_room_event()
    return Response(status_code=status.HTTP_201_CREATED)


@app.get("/api/state")
async def room_state(after: Optional[int] = Query(default=None, ge=0)):
    room = game.room

    # Если клиент запрашивает «после той же версии» — ждём новую,
    # но НЕ дольше STATE_LONGPOLL_SECONDS.
    if after is not None:
        try:
            async with state_condition:
                if room.state_version == after:
                    try:
                        await asyncio.wait_for(
                            state_condition.wait_for(
                                lambda: room.state_version != after
                            ),
                            timeout=STATE_LONGPOLL_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        pass  # отдадим текущее состояние — клиент переподключится
        except asyncio.CancelledError:
            raise

    # Тик ВНЕ state_condition — long-poll'ы других клиентов не блокируются.
    # _state_lock защищает от параллельных тиков.
    await _run_tick()

    # Снимок собираем под коротким локом, чтобы не пересечься с тиком.
    async with state_condition:
        return game.room_state(room)
