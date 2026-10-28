const board = document.querySelector("#board");
const ctx = board.getContext("2d");
const statusLabel = document.querySelector("#room-status");
const hint = document.querySelector("#hint");
const killsList = document.querySelector("#kills-list");

let state = null;
let stateVersion = null;
let lastRenderedVersion = -1;

// Управление циклом
let polling = false;
let inflightController = null;
let retryDelay = 500;      // ms; растёт при ошибках, сбрасывается при успехе
let stopped = false;

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

function fitCanvas() {
  const arena = board.parentElement;
  if (!arena) return false;
  const arenaRect = arena.getBoundingClientRect();
  if (arenaRect.width < 1 || arenaRect.height < 1) return false;

  const hintEl = arena.querySelector("#hint");
  const hintVisible = hintEl && getComputedStyle(hintEl).display !== "none";
  const hintH = hintVisible ? hintEl.getBoundingClientRect().height : 0;
  const gapPx = hintVisible ? 8 : 0;

  const availableW = arenaRect.width;
  const availableH = arenaRect.height - hintH - gapPx;
  if (availableW < 1 || availableH < 1) return false;

  const cssW = Math.min(availableW, availableH * 2);
  const cssH = cssW / 2;

  const dpr = window.devicePixelRatio || 1;
  const pixelsW = Math.max(1, Math.round(cssW * dpr));
  const pixelsH = Math.max(1, Math.round(cssH * dpr));

  if (board.width !== pixelsW) board.width = pixelsW;
  if (board.height !== pixelsH) board.height = pixelsH;
  board.style.width = cssW + "px";
  board.style.height = cssH + "px";
  return true;
}

function drawTile(type, x, y) {
  ctx.fillStyle = type === 4 ? "rgba(36,116,161,.85)" : tileColor(type);
  ctx.fillRect(x, y, 1, 1);
  if (type === 1) {
    ctx.fillStyle = "#b76537";
    ctx.fillRect(x + .06, y + .06, .88, .88);
    ctx.fillStyle = "#8d4b26";
    for (const [ox, oy, w, h] of [[.06, .06, .88, .26], [.06, .68, .88, .26], [.68, .06, .26, .88]]) {
      ctx.fillRect(x + ox, y + oy, w, h);
    }
    ctx.strokeStyle = "#754225";
    ctx.lineWidth = .045;
    ctx.strokeRect(x + .07, y + .07, .86, .86);
  } else if (type === 2) {
    ctx.fillStyle = "#c7d3da";
    ctx.fillRect(x + .12, y + .12, .76, .76);
    ctx.fillStyle = "#9aa8b0";
    ctx.fillRect(x + .04, y + .04, .92, .92);
    ctx.strokeStyle = "#78888f";
    ctx.lineWidth = .05;
    ctx.strokeRect(x + .04, y + .04, .92, .92);
  } else if (type === 5) {
    ctx.fillStyle = "#b8edf4";
    for (const [dx, dy] of [[.12, .18], [.2, .48], [.18, .76], [.7, .2], [.68, .52], [.74, .78]]) {
      ctx.beginPath();
      ctx.arc(x + dx, y + dy, .11, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function draw() {
  try {
    if (!state) {
      ctx.clearRect(0, 0, board.width, board.height);
      return;
    }
    const mapInfo = state.map || {};
    const mapWidth = mapInfo.width || 26;
    const mapHeight = mapInfo.height || 13;

    let tiles = Array.isArray(mapInfo.tiles) ? mapInfo.tiles : null;
    if (!tiles && Array.isArray(state.blocks)) {
      tiles = [];
      for (let y = 0; y < mapHeight; y++) tiles.push(new Array(mapWidth).fill(0));
      for (const b of state.blocks) tiles[b.y][b.x] = b.type;
    }
    if (!tiles || !tiles.length) return;

    if (!fitCanvas()) return;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = false;
    const scaleX = board.width / mapWidth;
    const scaleY = board.height / mapHeight;
    ctx.setTransform(scaleX, 0, 0, scaleY, 0, 0);

    ctx.fillStyle = "#111820";
    ctx.fillRect(0, 0, mapWidth, mapHeight);

    for (let y = 0; y < mapHeight; y++) {
      const row = tiles[y];
      if (!row) continue;
      for (let x = 0; x < mapWidth; x++) {
        const type = row[x];
        if (type) drawTile(type, x, y);
      }
    }
    for (const bonus of state.bonuses) drawBonus(bonus.type, bonus.x + .5, bonus.y + .5);
    for (const shell of state.shells) {
      ctx.fillStyle = "#fff4b8";
      ctx.beginPath();
      ctx.arc(shell.x, shell.y, .09, 0, Math.PI * 2);
      ctx.fill();
    }
    for (const tank of state.tanks) {
      if (!tank.alive) continue;
      drawTank(tank.x, tank.y, tank.direction, tank.is_bot, tank.shielded, tank.color);
    }
  } catch (err) {
    console.error("Ошибка отрисовки:", err);
  }
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
      const px = Math.cos(angle) * radius;
      const py = Math.sin(angle) * radius;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
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

function showKills(kills) {
  if (!killsList) return;
  const entries = Object.entries(kills || {});
  if (!entries.length) {
    killsList.innerHTML = '<li class="empty">Пока нет убийств</li>';
    return;
  }
  killsList.replaceChildren();
  for (const [name, count] of entries) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = name;
    const value = document.createElement("strong");
    value.textContent = String(count);
    item.append(label, value);
    killsList.append(item);
  }
}

// ---------------------------------------------------------------------------
// Сетевой цикл
// ---------------------------------------------------------------------------

async function fetchStateOnce() {
  const controller = new AbortController();
  inflightController = controller;

  // Страховочный таймаут: сервер отпускает long-poll за 25 с,
  // но если сеть «залипла» — рвём через 30 с.
  const timeoutId = setTimeout(() => controller.abort("timeout"), 30000);

  try {
    const after = stateVersion == null ? "" : `?after=${stateVersion}`;
    const response = await fetch(`/api/state${after}`, {
      signal: controller.signal,
      cache: "no-store",
      headers: { "Accept": "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Сервер ответил ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timeoutId);
    if (inflightController === controller) {
      inflightController = null;
    }
  }
}

async function pollLoop() {
  if (polling) return;
  polling = true;

  while (!stopped) {
    // Если вкладка не видна — не грузим сеть, но не выходим из цикла.
    if (document.hidden) {
      await new Promise(r => setTimeout(r, 500));
      continue;
    }

    try {
      const next = await fetchStateOnce();

      // «Устаревший» ответ — пропускаем.
      if (stateVersion != null && next.state_version === stateVersion) {
        // Сервер вернул ту же версию — значит, был таймаут long-poll.
        // Небольшая пауза, чтобы не спамить.
        await new Promise(r => setTimeout(r, 100));
        continue;
      }

      state = next;
      stateVersion = next.state_version;

      if (stateVersion !== lastRenderedVersion) {
        lastRenderedVersion = stateVersion;
        requestAnimationFrame(draw);
        showKills(next.kills);
        statusLabel.textContent = `Раунд идёт · танков: ${next.tanks_alive}`;
        hint.textContent = "Команды отправляются из терминального клиента.";
      }

      retryDelay = 500;
    } catch (error) {
      if (error.name === "AbortError") {
        // Наш собственный таймаут или abort по visibility — просто повтор.
        await new Promise(r => setTimeout(r, retryDelay));
        continue;
      }
      console.error("pollLoop:", error);
      statusLabel.textContent = error.message || "Ошибка сети";
      await new Promise(r => setTimeout(r, retryDelay));
      retryDelay = Math.min(5000, retryDelay * 2);
    }
  }
}

// При возврате на вкладку — сбрасываем возможные «залипшие» соединения.
document.addEventListener("visibilitychange", () => {
  if (inflightController) {
    try { inflightController.abort("visibility"); } catch (_) {}
    inflightController = null;
  }
  retryDelay = 500;
});

// Перезапуск при закрытии — на всякий случай.
window.addEventListener("pageshow", () => {
  stopped = false;
  if (!polling) pollLoop();
});

window.addEventListener("pagehide", () => {
  stopped = true;
  if (inflightController) {
    try { inflightController.abort("unload"); } catch (_) {}
    inflightController = null;
  }
});

window.addEventListener("resize", () => {
  requestAnimationFrame(draw);
});

// Старт
requestAnimationFrame(draw);
pollLoop();