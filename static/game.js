const select = document.querySelector("#room-select");
const board = document.querySelector("#board");
const ctx = board.getContext("2d");
const statusLabel = document.querySelector("#room-status");
const hint = document.querySelector("#hint");
const chat = document.querySelector("#chat");
const winsList = document.querySelector("#wins-list");
const STATE_POLL_INTERVAL_MS = 100;
const ROOM_LIST_POLL_INTERVAL_MS = 2000;
let state = null;
let previousTanks = new Map();
let receivedAt = 0;
let shownRoom = "";
let polling = false;

// Соответствие русских названий цветов (как их отдаёт сервер)
// и CSS-цветов для canvas. Canvas понимает только CSS-цвета,
// поэтому «красный» нужно превратить в «#e6194b» и т.д.
const TANK_COLOR_CSS = {
  "красный":    "#e6194b",
  "зелёный":    "#3cb44b",
  "синий":      "#4363d8",
  "оранжевый":  "#f58231",
  "фиолетовый": "#911eb4",
  "маджента":   "#f032e6",
  "лайм":       "#bfef45",
  "голубой":    "#42d4f4",
  "серый":      "#808080",
};

function colorToCss(color, isBot) {
  if (isBot) return TANK_COLOR_CSS["серый"];
  return TANK_COLOR_CSS[color] || TANK_COLOR_CSS["серый"];
}

function tileColor(type) {
  return ({ 1: "#b76537", 2: "#87939a", 3: "#2474a1", 4: "#397447", 5: "#a5e7ef", 6: "#e3b837" })[type] || "#111820";
}

function draw() {
  if (!state) {
    requestAnimationFrame(draw);
    return;
  }
  const mapWidth = state.map?.width || 26;
  const mapHeight = state.map?.height || 13;
  const canvasLeft = document.querySelector(".arena > #board") || board;
  const size = Math.min(canvasLeft.clientWidth || 800, canvasLeft.clientHeight || 600);
  if (!size) {
    requestAnimationFrame(draw);
    return;
  }
  const maxByHeight = (canvasLeft.clientHeight || 600) / mapHeight * mapWidth;
  const pixels = Math.min(Math.round(size * (window.devicePixelRatio || 1)), Math.round((canvasLeft.clientWidth || 800) * (window.devicePixelRatio || 1)), Math.round(maxByHeight * (window.devicePixelRatio || 1)));
  if (board.width !== pixels || board.height !== Math.round(pixels / mapWidth * mapHeight)) {
    board.width = pixels;
    board.height = Math.round(pixels / mapWidth * mapHeight);
  }
  const scale = pixels / mapWidth;
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.fillStyle = "#111820";
  ctx.fillRect(0, 0, mapWidth, mapHeight);

  for (const block of state.blocks) {
    ctx.fillStyle = block.type === 4 ? "rgba(36,116,161,.85)" : tileColor(block.type);
    ctx.fillRect(block.x, block.y, 1, 1);
    if (block.type === 1) {
      ctx.fillStyle = "#b76537";
      ctx.fillRect(block.x + .06, block.y + .06, .88, .88);
      ctx.fillStyle = "#8d4b26";
      for (const [ox, oy, w, h] of [[.06, .06, .88, .26], [.06, .68, .88, .26], [.68, .06, .26, .88]]) {
        ctx.fillRect(block.x + ox, block.y + oy, w, h);
      }
      ctx.strokeStyle = "#754225";
      ctx.lineWidth = .045;
      ctx.strokeRect(block.x + .07, block.y + .07, .86, .86);
    }
    if (block.type === 2) {
      ctx.fillStyle = "#c7d3da";
      ctx.fillRect(block.x + .12, block.y + .12, .76, .76);
      ctx.fillStyle = "#9aa8b0";
      ctx.fillRect(block.x + .04, block.y + .04, .92, .92);
      ctx.strokeStyle = "#78888f";
      ctx.lineWidth = .05;
      ctx.strokeRect(block.x + .04, block.y + .04, .92, .92);
    }
    if (block.type === 5) {
      ctx.fillStyle = "#b8edf4";
      for (const [dx, dy] of [[.12, .18], [.2, .48], [.18, .76], [.7, .2], [.68, .52], [.74, .78]]) {
        ctx.beginPath();
        ctx.arc(block.x + dx, block.y + dy, .11, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
  for (const bonus of state.bonuses) {
    drawBonus(bonus.type, bonus.x + .5, bonus.y + .5);
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
    drawTank(x, y, tank.direction, tank.is_bot, tank.shielded, tank.color);
  }
  const remaining = state && state.countdown_ends_at ? remainingSeconds(state, performance.now()) : null;
  if (remaining != null) {
    const remainingText = state.status === "countdown" ? Math.ceil(remaining).toString() : "0";
    ctx.font = "5px system-ui";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.shadowColor = "rgba(0,0,0,.85)";
    ctx.shadowBlur = .18;
    ctx.fillStyle = "#ffe96d";
    ctx.fillText(remainingText, mapWidth / 2, mapHeight / 2 - 1.5);
    ctx.shadowBlur = 0;
    ctx.font = ".65px system-ui";
    ctx.fillStyle = "#f3f6f8";
    ctx.fillText(state.status === "countdown" ? "СТАРТ ЧЕРЕЗ" : "РАУНД ИДЁТ", mapWidth / 2, mapHeight / 2 + .4);
  }
  requestAnimationFrame(draw);
}

function drawBonus(type, cx, cy) {
  if (type === "звезда") {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(Math.PI / 4);
    const outer = .20, inner = .085;
    ctx.fillStyle = "#ffe96d";
    ctx.strokeStyle = "#c9a227";
    ctx.lineWidth = .035;
    ctx.beginPath();
    for (let i = 0; i < 8; i += 1) {
      const radius = i % 2 === 0 ? outer : inner;
      const angle = Math.PI / 4 * i;
      const pointX = Math.cos(angle) * radius;
      const pointY = Math.sin(angle) * radius;
      if (i === 0) ctx.moveTo(pointX, pointY);
      else ctx.lineTo(pointX, pointY);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  } else {
    const colors = { шлем: "#72c1e9", часы: "#e3b8f2" };
    ctx.fillStyle = colors[type] || "#e3b8f2";
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = .025;
    ctx.beginPath();
    ctx.arc(cx, cy, .24, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}

function drawTank(x, y, direction, isBot, shielded, color) {
  const base = colorToCss(color, isBot);
  ctx.save();
  ctx.translate(x, y);
  if (direction === "вниз") ctx.rotate(Math.PI);
  else if (direction === "влево") ctx.rotate(-Math.PI / 2);
  else if (direction === "вправо") ctx.rotate(Math.PI / 2);
  ctx.fillStyle = shielded ? "#c6efff" : "#313c46";
  ctx.fillRect(-.34, -.34, .68, .68);
  ctx.strokeStyle = shielded ? "#ffffff" : "#141c22";
  ctx.lineWidth = .06;
  ctx.strokeRect(-.34, -.34, .68, .68);
  ctx.fillStyle = shielded ? "#c6efff" : base;
  ctx.fillRect(-.28, -.28, .56, .56);
  ctx.fillStyle = shielded ? "#ffffff" : "#d9e2e8";
  ctx.fillRect(-.18, -.18, .36, .36);
  ctx.fillStyle = shielded ? "#c6efff" : "#0f171d";
  ctx.fillRect(-.10, -.36, .20, .22);
  ctx.fillRect(-.30, -.62, .26, .36);
  ctx.fillRect(.04, -.62, .26, .36);
  ctx.fillStyle = shielded ? "#ffffff" : base;
  ctx.fillRect(-.30, -.62, .26, .20);
  ctx.fillRect(.04, -.62, .26, .20);
  ctx.restore();
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

function showWins(wins) {
  if (!winsList) return;
  const entries = Object.entries(wins || {});
  if (!entries.length) {
    winsList.innerHTML = '<li class="empty">Пока нет побед</li>';
    return;
  }
  winsList.replaceChildren();
  for (const [name, count] of entries) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = name;
    const value = document.createElement("strong");
    value.textContent = String(count);
    item.append(label, value);
    winsList.append(item);
  }
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

function remainingSeconds(next, now) {
  if (!next.countdown_ends_at) return null;
  const serverNow = (next.server_time || Date.now() / 1000) + (now - receivedAt) / 1000;
  return Math.max(0, next.countdown_ends_at - serverNow);
}

function countdownLabel(next) {
  const remaining = remainingSeconds(next, performance.now());
  return remaining == null ? "" : ` · старт через ${Math.ceil(remaining)} с`;
}

async function pollState() {
  if (polling) return;
  polling = true;
  try {
    const roomId = select.value;
    if (!roomId) {
      state = null;
      statusLabel.textContent = "Нет выбранной комнаты";
      showWins({});
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
    showWins(next.wins);
    statusLabel.textContent = `${next.status} · танков: ${next.tanks_alive}${countdownLabel(next)}`;
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