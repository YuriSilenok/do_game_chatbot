const list = document.querySelector("#rooms");
const errorLabel = document.querySelector("#admin-error");

async function refresh() {
  const response = await fetch("/api/rooms");
  const rooms = await response.json();
  if (!response.ok) throw new Error(rooms.detail || "Не удалось загрузить комнаты.");
  list.replaceChildren();
  for (const room of rooms) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${room.name} (#${room.id}) — ${room.status}; игроков: ${room.players}`;
    const remove = document.createElement("button");
    remove.textContent = "Удалить";
    remove.addEventListener("click", async () => {
      const result = await fetch(`/api/rooms/${encodeURIComponent(room.id)}`, { method: "DELETE" });
      if (!result.ok) {
        const body = await result.json();
        errorLabel.textContent = body.detail || "Не удалось удалить комнату.";
        return;
      }
      await refresh();
    });
    item.append(label, remove);
    list.append(item);
  }
}

document.querySelector("#create-room").addEventListener("submit", async event => {
  event.preventDefault();
  errorLabel.textContent = "";
  const name = document.querySelector("#room-name").value.trim();
  try {
    const response = await fetch("/api/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Не удалось создать комнату.");
    await refresh();
  } catch (error) {
    errorLabel.textContent = error.message;
  }
});

refresh().catch(error => { errorLabel.textContent = error.message; });
