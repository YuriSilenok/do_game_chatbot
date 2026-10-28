from __future__ import annotations

from url_server import ip_server, port

import asyncio
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from game import game


BASE_DIR = Path(__file__).resolve().parent
state_condition = asyncio.Condition()
room_wakeup = asyncio.Event()
room_task: Optional[asyncio.Task] = None


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class MessageRequest(BaseModel):
    sender: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=500)


app = FastAPI(title="Танковый чат")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


async def publish_room_event() -> None:
    global room_task
    room = game.room
    room.state_version += 1
    if room_task is None or room_task.done():
        room_task = asyncio.create_task(room_event_loop())
    room_wakeup.set()
    async with state_condition:
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
            game.process_room_events(game.room)
            game.room.state_version += 1
            async with state_condition:
                state_condition.notify_all()


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


@app.post("/api/messages", status_code=status.HTTP_201_CREATED)
async def send_message(payload: MessageRequest):
    room = game.room
    try:
        game.process_room_events(room)
        game.post_message(room, payload.sender, payload.text)
        game.process_room_events(room)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await publish_room_event()
    # Ничего не возвращаем — клиенту не нужен ответ.
    return Response(status_code=status.HTTP_201_CREATED)


@app.post("/api/commands", status_code=status.HTTP_201_CREATED)
async def send_command(payload: MessageRequest):
    room = game.room
    normalized = payload.text.strip().casefold()
    if normalized not in {"вверх", "вниз", "влево", "вправо", "выстрел"}:
        raise HTTPException(status_code=422, detail="Неизвестная команда.")
    try:
        game.process_room_events(room)
        game.post_message(room, payload.sender, normalized)
        game.process_room_events(room)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await publish_room_event()
    return Response(status_code=status.HTTP_201_CREATED)


@app.get("/api/state")
async def room_state(after: Optional[int] = Query(default=None, ge=0), get_messages: bool = False):
    room = game.room
    if after is not None and room.state_version == after:
        async with state_condition:
            await state_condition.wait_for(lambda: room.state_version != after)
    return game.room_state(get_messages)

if __name__ == "__main__":
    uvicorn.run(app, host=ip_server, port=port)
