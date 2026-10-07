import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from game import Game, TICK_SECONDS, game


BASE_DIR = Path(__file__).resolve().parent
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "tankcity"
security = HTTPBasic()


class RoomCreate(BaseModel):
    name: str = Field(default="Комната", min_length=1, max_length=60)


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class MessageRequest(BaseModel):
    sender: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=500)


def require_admin(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> None:
    user_ok = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    password_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль.",
            headers={"WWW-Authenticate": "Basic"},
        )


def find_room(room_id: str):
    room = game.rooms.get(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Комната не найдена.")
    return room


@asynccontextmanager
async def lifespan(_: FastAPI):
    async def game_loop() -> None:
        while True:
            game.tick()
            await asyncio.sleep(TICK_SECONDS)

    task = asyncio.create_task(game_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Танковый чат", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(BASE_DIR / "static" / "admin.html")


@app.get("/api/rooms")
async def list_rooms():
    return [game.room_summary(room) for room in game.rooms.values()]


@app.post("/api/rooms", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_room(payload: RoomCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название комнаты не может быть пустым.")
    return game.room_summary(game.create_room(name))


@app.delete("/api/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_room(room_id: str):
    if not game.delete_room(room_id):
        raise HTTPException(status_code=404, detail="Комната не найдена.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, payload: JoinRequest):
    room = find_room(room_id)
    try:
        game.join(room, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return game.room_summary(room)


@app.post("/api/rooms/{room_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(room_id: str, payload: MessageRequest):
    room = find_room(room_id)
    try:
        return game.post_message(room, payload.sender, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/rooms/{room_id}/commands", status_code=status.HTTP_201_CREATED)
async def send_command(room_id: str, payload: MessageRequest):
    room = find_room(room_id)
    normalized = payload.text.strip().casefold()
    if normalized not in {"вверх", "вниз", "влево", "вправо", "выстрел"}:
        raise HTTPException(status_code=422, detail="Неизвестная команда.")
    try:
        return game.post_message(room, payload.sender, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/rooms/{room_id}/state")
async def room_state(room_id: str):
    return game.room_state(find_room(room_id))
