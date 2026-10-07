const select = document.querySelector("#room-select");
const board = document.querySelector("#board");
const ctx = board.getContext("2d");
const statusLabel = document.querySelector("#room-status");
const hint = document.querySelector("#hint");
const chat = document.querySelector("#chat");
const STATE_POLL_INTERVAL_MS = 100;
const ROOM_LIST_POLL_INTERVAL_MS = 2000;
let state = null;
let previousTanks = new Map();
let receivedAt = 0;
let shownRoom = "";
let polling = false;

function tileColor(type) {
  return ({ 1: "#b76537", 2: "#87939a", 3: "#2474a1", 4: "#397447", 5: "#a5e7ef", 6: "#e3b837" })[type] || "#111820";
}

function draw() {
  const size = Math.min(board.clientWidth, board.clientHeight);
  if (!size) return;
  const ratio = window.devicePixelRatio || 1;
  const pixels = Math.round(size * ratio);
  if (board.width !== pixels || board.height !== pixels) {
    board.width = pixels;
    board.height = pixels;
  }
  ctx.setTransform(pixels / 13, 0, 0, pixels / 13, 0, 0);
  ctx.fillStyle = "#111820";
  ctx.fillRect(0, 0, 13, 13);

  if (!state) {
    requestAnimationFrame(draw);
    return;
  }
  for (const block of state.blocks) {
    ctx.fillStyle = tileColor(block.type);
    ctx.fillRect(block.x + .04, block.y + .04, .92, .92);
    if (block.type === 1) {
      ctx.strokeStyle = "#754225";
      ctx.lineWidth = .045;
      ctx.strokeRect(block.x + .08, block.y + .08, .84, .84);
    }
    if (block.type === 4) {
      ctx.fillStyle = "#183c24";
      ctx.beginPath();
      ctx.arc(block.x + .5, block.y + .5, .13, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  for (const bonus of state.bonuses) {
    ctx.fillStyle = bonus.type === "звезда" ? "#ffe96d" : bonus.type === "шлем" ? "#90eaff" : "#e8b4ff";
    ctx.beginPath();
    ctx.arc(bonus.x + .5, bonus.y + .5, .22, 0, Math.PI * 2);
    ctx.fill();
  }
  for (const shell of state.shells) {
    ctx.fillStyle = "#fff4b8";
    ctx.beginPath();
    ctx.arc(shell.x, shell.y, .09, 0, Math.PI * 2);
    ctx.fill();
  }
  const interpolation = Math.min(1, (performance.now() - receivedAt) / 100);
  for (const tank of state.tanks) {
    if (!tank.alive) continue;
    const from = previousTanks.get(tank.id) || tank;
    const x = from.x + (tank.x - from.x) * interpolation;
    const y = from.y + (tank.y - from.y) * interpolation;
    const color = tank.is_bot ? "#e07e42" : "#55c7a4";
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(({ вверх: 0, вправо: Math.PI / 2, вниз: Math.PI, влево: -Math.PI / 2 })[tank.direction] || 0);
    ctx.fillStyle = tank.shielded ? "#c6efff" : color;
    ctx.fillRect(-.29, -.29, .58, .58);
    ctx.fillStyle = "#172029";
    ctx.fillRect(-.08, -.37, .16, .31);
    ctx.restore();
    ctx.fillStyle = "#fff";
    ctx.font = ".16px system-ui";
    ctx.textAlign = "center";
    ctx.fillText(tank.name, x, y - .38);
  }
  for (const block of state.blocks) {
    if (block.type !== 4) continue;
    ctx.fillStyle = "#397447";
    ctx.fillRect(block.x + .04, block.y + .04, .92, .92);
    ctx.fillStyle = "#244f32";
    for (const [dx, dy] of [[.25, .28], [.68, .4], [.42, .72]]) {
      ctx.beginPath();
      ctx.arc(block.x + dx, block.y + dy, .13, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  requestAnimationFrame(draw);
}

function showMessages(messages, roomId) {
  if (shownRoom !== roomId) {
    chat.replaceChildren();
    shownRoom = roomId;
  }
  const latest = Number(chat.dataset.latest || 0);
  for (const message of messages) {
    if (message.id <= latest) continue;
    const item = document.createElement("li");
    if (message.is_command) item.className = "command";
    item.textContent = `${message.sender}: ${message.text}`;
    chat.append(item);
  }
  if (messages.length) chat.dataset.latest = String(messages[messages.length - 1].id);
  while (chat.children.length > 200) chat.firstElementChild.remove();
  chat.scrollTop = chat.scrollHeight;
}

async function loadRooms() {
  const response = await fetch("/api/rooms");
  if (!response.ok) throw new Error("Не удалось загрузить список комнат.");
  const rooms = await response.json();
  const selected = select.value;
  select.replaceChildren(new Option("Выберите комнату", ""));
  for (const room of rooms) select.add(new Option(`${room.name} (#${room.id}) — ${room.status}`, room.id));
  if (rooms.some(room => room.id === selected)) select.value = selected;
  else if (rooms.length && !selected) select.value = rooms[0].id;
}

async function pollState() {
  if (polling) return;
  polling = true;
  try {
    const roomId = select.value;
    if (!roomId) {
      state = null;
      statusLabel.textContent = "Нет выбранной комнаты";
      return;
    }
    const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}/state`);
    if (!response.ok) throw new Error("Не удалось получить состояние комнаты.");
    const next = await response.json();
    if (roomId !== select.value) return;
    previousTanks = new Map((state?.tanks || []).map(tank => [tank.id, tank]));
    state = next;
    receivedAt = performance.now();
    showMessages(next.messages, roomId);
    const countdown = next.countdown_ends_at
      ? ` · старт через ${Math.max(0, Math.ceil(next.countdown_ends_at - Date.now() / 1000))} с`
      : "";
    statusLabel.textContent = `${next.status} · танков: ${next.tanks_alive}${countdown}`;
    hint.textContent = next.status === "waiting"
      ? "Для регистрации отправьте в терминальном клиенте: «войти " + roomId + " Имя»."
      : next.status === "countdown"
        ? "Регистрация открыта. Танки появятся после отсчёта."
        : "Раунд идёт. Команды доступны через терминальный клиент.";
  } finally {
    polling = false;
  }
}

select.addEventListener("change", () => {
  shownRoom = "";
  chat.dataset.latest = "0";
  pollState().catch(error => { statusLabel.textContent = error.message; });
});

loadRooms().then(pollState).catch(error => { statusLabel.textContent = error.message; });
setInterval(() => loadRooms().catch(error => { statusLabel.textContent = error.message; }), ROOM_LIST_POLL_INTERVAL_MS);
setInterval(() => pollState().catch(error => { statusLabel.textContent = error.message; }), STATE_POLL_INTERVAL_MS);
window.addEventListener("resize", draw);
draw();
