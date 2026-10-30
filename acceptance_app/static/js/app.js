/* SPA «Сдача-приёмка квартир». Vanilla JS, без сборщиков. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  token: localStorage.getItem("token") || "",
  user: null,
  meta: null,
  objects: [],
  currentObject: null,
  currentRoomId: null,
  openBuilding: null,
};

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  let method = opts.method || (opts.json !== undefined || opts.body !== undefined ? "POST" : "GET");
  method = method.toUpperCase();
  let body;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.body !== undefined) {
    body = opts.body; // FormData — Content-Type ставит браузер
  }
  const init = { ...opts, method, headers };
  if (body !== undefined && method !== "GET" && method !== "HEAD") init.body = body;
  delete init.json;
  const resp = await fetch(path, init);
  if (resp.status === 401 && !path.includes("/login")) { doLogout(false); throw new Error("Сессия истекла"); }
  if (!resp.ok) {
    let msg = "Ошибка " + resp.status;
    try { const j = await resp.json(); if (j.detail) msg = j.detail; } catch (e) {}
    throw new Error(msg);
  }
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("json") ? resp.json() : resp;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 3200);
}

/* ---------- модальные окна ---------- */
let modalResolve = null;
function showModal(title, bodyHtml, okText = "Сохранить") {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = bodyHtml;
  $("#modal-ok").textContent = okText;
  $("#modal-overlay").classList.remove("hidden");
  return new Promise(res => { modalResolve = res; });
}
function closeModal(val) {
  $("#modal-overlay").classList.add("hidden");
  if (modalResolve) { modalResolve(val); modalResolve = null; }
}
$("#modal-cancel").onclick = () => closeModal(null);
$("#modal-ok").onclick = () => closeModal($("#modal-body"));
$("#modal-overlay").onclick = (e) => { if (e.target.id === "modal-overlay") closeModal(null); };

async function confirmBox(text) {
  const body = `<p>${esc(text)}</p>`;
  const r = await showModal("Подтверждение", body, "Да, выполнить");
  return r !== null;
}

/* ---------- авторизация ---------- */
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    const res = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("#login-username").value.trim(), password: $("#login-password").value }),
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.detail || "Ошибка входа");
    state.token = j.token; localStorage.setItem("token", j.token);
    state.user = j.user;
    enterApp();
  } catch (err) { $("#login-error").textContent = err.message; }
});

function doLogout(callApi = true) {
  if (callApi) fetch("/api/logout", { method: "POST" }).catch(() => {});
  localStorage.removeItem("token"); state.token = ""; state.user = null;
  $("#app-screen").classList.add("hidden");
  $("#login-screen").classList.remove("hidden");
}
$("#btn-logout").onclick = () => doLogout();

/* ---------- уровни доступа в UI ---------- */
function applyLevels() {
  const lvl = state.user.access_level;
  document.querySelectorAll(".lvl2").forEach(el => el.classList.toggle("hidden", lvl < 2));
  document.querySelectorAll(".lvl3").forEach(el => el.classList.toggle("hidden", lvl < 3));
  $("#user-name").textContent = state.user.full_name || state.user.username;
  $("#user-level").textContent = "уровень " + lvl;
  $("#btn-admin").classList.toggle("hidden", lvl < 3);
  $("#btn-backup").classList.toggle("hidden", lvl < 3);
  $("#btn-restore").classList.toggle("hidden", lvl < 3);
}

/* ---------- навигация ---------- */
const views = ["view-objects", "view-object", "view-room", "view-admin"];
function showView(name) {
  views.forEach(v => $("#" + v).classList.toggle("hidden", v !== name));
}
function crumbs(items) {
  $("#breadcrumbs").innerHTML = items.map((it, i) =>
    i === items.length - 1 ? `<span>${esc(it.label)}</span>`
      : `<a data-nav="${esc(JSON.stringify(it.nav || {}))}">${esc(it.label)}</a> / `).join("");
  $("#breadcrumbs").querySelectorAll("a").forEach(a => {
    a.onclick = () => {
      const nav = JSON.parse(a.dataset.nav);
      if (nav.objects) goObjects();
      else if (nav.object) goObject(nav.object);
    };
  });
}

/* ---------- список объектов ---------- */
async function goObjects() {
  showView("view-objects");
  crumbs([{ label: "Объекты", nav: { objects: true } }]);
  await loadObjects();
}

async function loadObjects() {
  state.objects = await api("/api/objects");
  const wrap = $("#objects-list");
  wrap.innerHTML = "";
  if (!state.objects.length) wrap.innerHTML = `<div class="card muted">Объектов пока нет.</div>`;
  for (const o of state.objects) {
    const card = document.createElement("div");
    card.className = "card obj-card";
    card.innerHTML = `<h3>${esc(o.name)}</h3>
      <div class="muted small">${esc(o.description || "")}</div>
      <div class="total-tag">Корпусов: ${o.buildings_count} · Помещений: ${o.stats.total}</div>
      <div class="stat-line">${chipsHtml(o.stats)}</div>`;
    card.onclick = () => goObject(o.id);
    wrap.appendChild(card);
  }
}

function chipsHtml(stats) {
  return stats.by_status.map(s =>
    `<span class="chip ${s.count ? "" : "zero"}" style="background:${s.color}" title="${esc(s.label)}">${esc(s.label)}: ${s.count}</span>`
  ).join("");
}

/* ---------- объект: корпуса + шахматка ---------- */
async function goObject(oid) {
  showView("view-object");
  const o = await api(`/api/objects/${oid}`);
  state.currentObject = o;
  crumbs([{ label: "Объекты", nav: { objects: true } }, { label: o.name }]);
  $("#object-title").textContent = o.name;
  $("#object-desc").textContent = o.description || "";
  renderEmployees(o);
  renderBuildings(o);
}

function renderEmployees(o) {
  const box = $("#object-employees");
  box.innerHTML = `<b class="muted small">Прикреплённые сотрудники:</b>` +
    (o.employees.map(e =>
      `<span class="emp-chip">${esc(e.full_name || e.username)} (${e.access_level})
        <button data-aid="${e.assignment_id}" title="Открепить">✕</button></span>`).join("") ||
      `<span class="muted small">никто не прикреплён</span>`) +
    `<button class="btn sm" id="btn-assign-emp">+ сотрудник</button>`;
  box.querySelectorAll("button[data-aid]").forEach(b => {
    b.onclick = async (ev) => {
      ev.stopPropagation();
      if (await confirmBox("Открепить сотрудника от объекта?")) {
        await api(`/api/objects/${o.id}/employees/${b.dataset.aid}`, { method: "DELETE" });
        goObject(o.id);
      }
    };
  });
  $("#btn-assign-emp").onclick = () => assignEmployeeDialog(o.id);
}

async function assignEmployeeDialog(oid) {
  const emps = await api("/api/employees");
  const body = `<label>Выберите сотрудника<select id="mp-sel">` +
    emps.map(e => `<option value="${e.id}">${esc(e.full_name || e.username)} — ур.${e.access_level}</option>`).join("") +
    `</select></label>`;
  const r = await showModal("Прикрепить сотрудника к объекту", body);
  if (r) {
    const id = Number(r.querySelector("#mp-sel").value);
    await api(`/api/objects/${oid}/employees`, { json: { employee_id: id } });
    toast("Сотрудник прикреплён"); goObject(oid);
  }
}

function renderBuildings(o) {
  const wrap = $("#buildings-accordion");
  wrap.innerHTML = "";
  for (const b of o.buildings) {
    const item = document.createElement("div");
    item.className = "building-item" + (state.openBuilding === b.id ? " open" : "");
    item.innerHTML = `
      <div class="building-head">
        <span class="arrow">▶</span>
        <b>${esc(b.name)}</b>
        <span class="muted small">${esc(b.address)} · этажей: ${b.floors} · квартир на этаж: ${b.apartments_per_floor}</span>
        <span class="total-tag">помещений: ${b.stats.total}</span>
        <span class="stat-line">${chipsHtml(b.stats)}</span>
        <span class="bld-actions lvl3">
          <button class="btn sm" data-act="edit">✏️</button>
          <button class="btn sm danger" data-act="del">🗑</button>
        </span>
      </div>
      <div class="building-body hidden"></div>`;
    const head = item.querySelector(".building-head");
    head.onclick = async (e) => {
      if (e.target.closest(".bld-actions")) return;
      const body = item.querySelector(".building-body");
      const opening = body.classList.contains("hidden");
      wrap.querySelectorAll(".building-body").forEach(x => x.classList.add("hidden"));
      wrap.querySelectorAll(".building-item").forEach(x => x.classList.remove("open"));
      if (opening) {
        body.classList.remove("hidden"); item.classList.add("open");
        state.openBuilding = b.id;
        if (!body.dataset.loaded) { await renderChess(body, b.id); body.dataset.loaded = "1"; }
      } else state.openBuilding = null;
    };
    item.querySelector('[data-act="edit"]').onclick = (e) => { e.stopPropagation(); buildingDialog(o.id, b); };
    item.querySelector('[data-act="del"]').onclick = async (e) => {
      e.stopPropagation();
      if (await confirmBox(`Удалить корпус «${b.name}» со всеми помещениями и историями?`)) {
        await api(`/api/buildings/${b.id}`, { method: "DELETE" });
        goObject(o.id);
      }
    };
    wrap.appendChild(item);
    if (state.openBuilding === b.id) head.click();
  }
  const addBtn = document.createElement("button");
  addBtn.className = "btn mt lvl3"; addBtn.textContent = "+ Добавить корпус";
  addBtn.onclick = () => buildingDialog(o.id, null);
  wrap.appendChild(addBtn);
  applyLevels();
}

async function renderChess(body, bid) {
  body.innerHTML = `<div class="legend">` +
    state.meta.room_statuses.map(s => `<span><i class="dot" style="background:${s.color}"></i>${esc(s.label)}</span>`).join("") +
    `<span class="muted">— пунктирная рамка: нежилое помещение</span></div><div class="chess">Загрузка…</div>`;
  const rooms = await api(`/api/buildings/${bid}/rooms`);
  const byFloor = {};
  rooms.forEach(r => { (byFloor[r.floor] ||= []).push(r); });
  const chess = body.querySelector(".chess");
  chess.innerHTML = "";
  const floors = Object.keys(byFloor).map(Number).sort((a, b) => b - a); // сверху вниз
  for (const fl of floors) {
    const row = document.createElement("div");
    row.className = "floor-row";
    row.innerHTML = `<span class="floor-label">Этаж ${fl}</span>`;
    const balls = document.createElement("div");
    balls.className = "balls";
    byFloor[fl].sort((a, b) => Number(a.number) - Number(b.number) || a.number.localeCompare(b.number))
      .forEach(r => {
        const ball = document.createElement("div");
        ball.className = "ball" + (r.kind === "non_residential" ? " non-res" : "");
        ball.style.background = r.status_color;
        ball.textContent = r.number;
        ball.title = `Кв. ${r.number}: ${r.status_label}` +
          (r.open_violations ? ` · открытых нарушений: ${r.open_violations}` : "");
        ball.onclick = () => goRoom(r.id);
        balls.appendChild(ball);
      });
    row.appendChild(balls);
    chess.appendChild(row);
  }
  if (!floors.length) chess.innerHTML = `<span class="muted">Помещений нет. Добавьте вручную или сгенерируйте через ✏️ корпуса.</span>`;
}

function buildingFormHtml(b) {
  b = b || { name: "", address: "", floors: 5, apartments_per_floor: 4 };
  return `
    <label>Название корпуса<input id="bf-name" value="${esc(b.name)}" placeholder="Корпус 1"></label>
    <label>Адрес<input id="bf-address" value="${esc(b.address)}"></label>
    <div class="form-grid">
      <label>Этажей<input id="bf-floors" type="number" min="1" max="200" value="${b.floors}"></label>
      <label>Квартир на этаж<input id="bf-per" type="number" min="1" max="100" value="${b.apartments_per_floor}"></label>
    </div>
    ${b.id ? `<p class="muted small">Изменение этажности добавляет недостающие квартиры; лишние не удаляются.</p>`
           : `<label><input type="checkbox" id="bf-gen" checked style="width:auto"> Автоматически создать квартиры (${b.floors * b.apartments_per_floor} шт.)</label>`}`;
}

async function buildingDialog(oid, b) {
  const r = await showModal(b ? "Редактировать корпус" : "Новый корпус", buildingFormHtml(b));
  if (!r) return;
  const data = {
    name: r.querySelector("#bf-name").value.trim(),
    address: r.querySelector("#bf-address").value.trim(),
    floors: Number(r.querySelector("#bf-floors").value),
    apartments_per_floor: Number(r.querySelector("#bf-per").value),
  };
  if (!data.name) return toast("Укажите название корпуса");
  try {
    if (b) {
      await api(`/api/buildings/${b.id}`, { json: data });
      if (data.floors * data.apartments_per_floor > b.floors * b.apartments_per_floor) {
        await fetch(`/api/buildings/${b.id}/generate?floors=${data.floors}&per_floor=${data.apartments_per_floor}`, {
          method: "POST", headers: { "Authorization": "Bearer " + state.token } });
      }
    } else {
      data.generate_rooms = !!r.querySelector("#bf-gen")?.checked;
      await api(`/api/objects/${oid}/buildings`, { json: data });
    }
    toast("Сохранено"); goObject(oid);
  } catch (e) { toast(e.message); }
}

/* ---------- объекты: создание/редактирование ---------- */
$("#btn-add-object").onclick = () => objectDialog(null);
$("#btn-edit-object").onclick = () => objectDialog(state.currentObject);
$("#btn-del-object").onclick = async () => {
  const o = state.currentObject;
  if (await confirmBox(`Удалить объект «${o.name}» со всеми корпусами, помещениями и историями?`)) {
    await api(`/api/objects/${o.id}`, { method: "DELETE" });
    toast("Объект удалён"); goObjects();
  }
};

function objectFormHtml(o) {
  o = o || { name: "", description: "" };
  return `<label>Название объекта<input id="of-name" value="${esc(o.name)}" placeholder="ЖК «...»"></label>
          <label>Описание<textarea id="of-desc" rows="2">${esc(o.description)}</textarea></label>`;
}

async function objectDialog(o) {
  const r = await showModal(o ? "Редактировать объект" : "Новый объект", objectFormHtml(o));
  if (!r) return;
  const data = { name: r.querySelector("#of-name").value.trim(), description: r.querySelector("#of-desc").value.trim() };
  if (!data.name) return toast("Укажите название");
  try {
    if (o) { await api(`/api/objects/${o.id}`, { json: data }); toast("Сохранено"); goObject(o.id); }
    else { const res = await api("/api/objects", { json: data }); toast("Объект создан"); goObject(res.id); }
  } catch (e) { toast(e.message); }
}

/* ---------- карточка помещения ---------- */
async function goRoom(rid) {
  showView("view-room");
  const r = await api(`/api/rooms/${rid}`);
  state.currentRoomId = rid;
  crumbs([
    { label: "Объекты", nav: { objects: true } },
    { label: r.object.name, nav: { object: r.object.id } },
    { label: `${r.building.name}, кв. ${r.number}` },
  ]);
  $("#room-title").textContent = `Помещение № ${r.number} — ${r.building.name}`;
  const pill = $("#room-status-pill");
  pill.textContent = r.status_label; pill.style.background = r.status_color;

  $("#room-fields").innerHTML = [
    ["Объект", r.object.name],
    ["Корпус / адрес", `${r.building.name}, ${r.building.address}`],
    ["Этаж", r.floor],
    ["Тип помещения", r.kind_label],
    ["Отделка", r.finish_label],
    ["Площадь", r.area ? r.area + " м²" : "—"],
    ["Покупатель", r.buyer_info || "—"],
    ["Нарушений", `${r.violations_count} (открытых: ${r.open_violations})`],
  ].map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");

  // акт
  const dl = $("#btn-download-act");
  if (r.acceptance_act_filename) {
    $("#act-current").innerHTML = `📄 <b>${esc(r.acceptance_act_filename)}</b>`;
    dl.classList.remove("hidden");
    dl.href = `/api/rooms/${r.id}/act`;
    dl.setAttribute("download", "");
    dl.onclick = (e) => { e.preventDefault(); authedDownload(dl.href); };
  } else {
    $("#act-current").textContent = "Не прикреплён";
    dl.classList.add("hidden");
  }

  $("#room-editor").classList.add("hidden");
  fillSelect("#ed-kind", state.meta.premises_kinds, r.kind);
  fillSelect("#ed-finish", state.meta.finish_types, r.finish_type);
  fillSelect("#ed-status", state.meta.room_statuses, r.status);
  $("#ed-number").value = r.number; $("#ed-floor").value = r.floor;
  $("#ed-area").value = r.area || 0; $("#ed-buyer").value = r.buyer_info || "";

  renderViolations(r);
  applyLevels();
}

function fillSelect(sel, items, val) {
  const el = $(sel);
  el.innerHTML = items.map(i => `<option value="${i.key}" ${i.key === val ? "selected" : ""}>${esc(i.label)}</option>`).join("");
}

$("#btn-edit-room").onclick = () => $("#room-editor").classList.toggle("hidden");
$("#ed-cancel").onclick = () => $("#room-editor").classList.add("hidden");
$("#ed-save").onclick = async () => {
  try {
    await api(`/api/rooms/${state.currentRoomId}`, { json: {
      number: $("#ed-number").value.trim(), floor: Number($("#ed-floor").value),
      kind: $("#ed-kind").value, finish_type: $("#ed-finish").value,
      status: $("#ed-status").value, area: Number($("#ed-area").value),
      buyer_info: $("#ed-buyer").value.trim(),
    }});
    toast("Помещение сохранено"); goRoom(state.currentRoomId);
  } catch (e) { toast(e.message); }
};

$("#btn-upload-act").onclick = async () => {
  const f = $("#act-file").files[0];
  if (!f) return toast("Выберите файл акта");
  const fd = new FormData(); fd.append("file", f);
  try {
    await api(`/api/rooms/${state.currentRoomId}/act`, { method: "POST", body: fd });
    toast("Акт прикреплён"); goRoom(state.currentRoomId);
  } catch (e) { toast(e.message); }
};

async function authedDownload(url) {
  const resp = await fetch(url, { headers: { "Authorization": "Bearer " + state.token } });
  if (!resp.ok) return toast("Файл недоступен");
  const blob = await resp.blob();
  const cd = resp.headers.get("content-disposition") || "";
  const m = cd.match(/filename="?([^";]+)"?/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = m ? m[1] : "file";
  a.click(); URL.revokeObjectURL(a.href);
}

/* ---------- нарушения и история ---------- */
function renderViolations(room) {
  const box = $("#violations-list");
  box.innerHTML = "";
  if (!room.violations.length) {
    box.innerHTML = `<p class="muted">Нарушений нет. Добавьте первое нарушение кнопкой «➕ Нарушение».</p>`;
    return;
  }
  for (const v of room.violations) {
    const card = document.createElement("div");
    card.className = "violation-card";
    card.innerHTML = `
      <div class="v-head">
        <span class="v-title">${esc(v.title)}</span>
        <span class="pill" style="background:${v.status_color}">${esc(v.status_label)}</span>
        <span class="t-meta">создано ${new Date(v.created_at).toLocaleString("ru-RU")}</span>
      </div>
      <div class="v-status-btns lvl2 hidden">
        ${state.meta.violation_statuses.map(s =>
          `<button class="btn ${v.status === s.key ? "active" : ""}" style="background:${s.color}"
             data-v="${v.id}" data-s="${s.key}" title="Перевести: ${esc(s.label)}">${esc(s.label)}</button>`).join("")}
      </div>
      <div class="timeline">
        ${v.events.map(ev => eventHtml(ev)).join("")}
      </div>
      <div class="lvl2 hidden">
        <button class="btn sm add-ev" data-v="${v.id}">＋ Запись в историю</button>
        <div class="add-event-form hidden" data-form="${v.id}">
          <label>Тип<div class="row"><span><input type="radio" name="k${v.id}" value="inspection" checked style="width:auto"> осмотр / нарушение</span>
                <span><input type="radio" name="k${v.id}" value="fix" style="width:auto"> исправление</span></div></label>
          <label>Текст<textarea rows="2" class="ev-text"></textarea></label>
          <label>Фото<input type="file" accept="image/*" class="ev-photo"></label>
          <button class="btn primary sm send-ev" data-v="${v.id}">Добавить запись</button>
        </div>
      </div>`;
    box.appendChild(card);
  }
  // обработчики статусов
  box.querySelectorAll(".v-status-btns .btn").forEach(b => {
    b.onclick = async () => {
      try {
        await api(`/api/violations/${b.dataset.v}/status`, { json: { status: b.dataset.s } });
        toast("Статус обновлён"); goRoom(room.id);
      } catch (e) { toast(e.message); }
    };
  });
  box.querySelectorAll(".add-ev").forEach(b => {
    b.onclick = () => box.querySelector(`[data-form="${b.dataset.v}"]`).classList.toggle("hidden");
  });
  box.querySelectorAll(".send-ev").forEach(b => {
    b.onclick = async () => {
      const form = box.querySelector(`[data-form="${b.dataset.v}"]`);
      const kind = form.querySelector(`input[name="k${b.dataset.v}"]:checked`).value;
      const text = form.querySelector(".ev-text").value.trim();
      const file = form.querySelector(".ev-photo").files[0];
      if (!text && !file) return toast("Укажите текст или фото");
      const fd = new FormData();
      fd.append("kind", kind); fd.append("text", text);
      if (file) fd.append("photo", file);
      try {
        await api(`/api/violations/${b.dataset.v}/events`, { method: "POST", body: fd });
        toast("Запись добавлена в историю"); goRoom(room.id);
      } catch (e) { toast(e.message); }
    };
  });
  box.querySelectorAll(".t-photo").forEach(img => {
    img.onclick = () => { $("#lightbox-img").src = img.src; $("#lightbox").classList.remove("hidden"); };
  });
}

function eventHtml(ev) {
  const isFix = ev.kind === "fix";
  return `<div class="t-event ${isFix ? "fix" : ""}">
    <div class="t-kind">${isFix ? "🟢 Фото/запись исправления" : "🔴 Осмотр: нарушение"}</div>
    ${ev.text ? `<div>${esc(ev.text)}</div>` : ""}
    ${ev.photo ? `<img class="t-photo" src="/uploads/${encodeURIComponent(ev.photo)}" alt="фото">` : ""}
    <div class="t-meta">${esc(ev.author)} · ${new Date(ev.created_at).toLocaleString("ru-RU")}${ev.photo_original ? " · " + esc(ev.photo_original) : ""} · удалить запись нельзя</div>
  </div>`;
}

$("#btn-add-violation").onclick = async () => {
  const body = `
    <label>Название нарушения<input id="vf-title" placeholder="Напр.: вздутие стены в кухне"></label>
    <label>Статус<select id="vf-status">${state.meta.violation_statuses.map(s =>
      `<option value="${s.key}">${esc(s.label)}</option>`).join("")}</select></label>
    <label>Текст осмотра<textarea id="vf-text" rows="2"></textarea></label>
    <label>Фото нарушения<input id="vf-photo" type="file" accept="image/*"></label>`;
  const r = await showModal("Новое нарушение", body);
  if (!r) return;
  const fd = new FormData();
  fd.append("title", r.querySelector("#vf-title").value.trim() || "Нарушение");
  fd.append("status", r.querySelector("#vf-status").value);
  fd.append("text", r.querySelector("#vf-text").value.trim());
  const f = r.querySelector("#vf-photo").files[0];
  if (f) fd.append("photo", f);
  try {
    await api(`/api/rooms/${state.currentRoomId}/violations`, { method: "POST", body: fd });
    toast("Нарушение создано"); goRoom(state.currentRoomId);
  } catch (e) { toast(e.message); }
};

/* ---------- администрирование ---------- */
$("#btn-admin").onclick = async () => {
  showView("view-admin");
  crumbs([{ label: "Объекты", nav: { objects: true } }, { label: "Администрирование" }]);
  const emps = await api("/api/employees");
  const lvlNames = { 1: "просмотр", 2: "инспектор", 3: "администратор" };
  $("#employees-table").innerHTML = `<tr><th>Логин</th><th>ФИО</th><th>Уровень</th><th>Статус</th><th></th></tr>` +
    emps.map(e => `<tr><td>${esc(e.username)}</td><td>${esc(e.full_name)}</td>
      <td>${e.access_level} · ${lvlNames[e.access_level]}</td>
      <td>${e.is_active ? "✅" : "🚫"}</td>
      <td><button class="btn sm" data-id="${e.id}">🔑 сброс пароля</button></td></tr>`).join("");
  $("#employees-table").querySelectorAll("button").forEach(b => {
    b.onclick = async () => {
      const body = `<label>Новый пароль<input id="np-pass" type="text"></label>`;
      const r = await showModal("Сброс пароля", body, "Сменить");
      if (r) {
        const p = r.querySelector("#np-pass").value;
        if (!p) return toast("Пустой пароль");
        try { await api(`/api/employees/${b.dataset.id}?password=${encodeURIComponent(p)}`, { method: "PATCH", json: {} }); toast("Пароль изменён"); }
        catch (e) { toast(e.message); }
      }
    };
  });
};

$("#btn-add-employee").onclick = async () => {
  try {
    await api("/api/employees", { json: {
      username: $("#nu-username").value.trim(), password: $("#nu-password").value,
      full_name: $("#nu-fullname").value.trim(), access_level: Number($("#nu-level").value),
    }});
    toast("Сотрудник добавлен");
    $("#nu-username").value = $("#nu-password").value = $("#nu-fullname").value = "";
    $("#btn-admin").click();
  } catch (e) { toast(e.message); }
};

/* ---------- бекап ---------- */
function downloadBackup() { authedDownload("/api/backup"); }
$("#btn-backup").onclick = downloadBackup;
$("#btn-backup2").onclick = downloadBackup;

$("#btn-restore").onclick = () => $("#btn-restore2").click();
$("#btn-restore2").onclick = async () => {
  const f = $("#restore-file").files[0];
  if (!f) return toast("Выберите zip-файл бекапа");
  if (!await confirmBox("Восстановить из бекапа? ТЕКУЩИЕ ДАННЫЕ БУДУТ ПОЛНОСТЬЮ ЗАМЕЩЕНЫ!")) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const res = await api("/api/restore", { method: "POST", body: fd });
    toast(`Восстановлено: помещений — ${res.counts.rooms}, нарушений — ${res.counts.violations}, файлов — ${res.restored_files}`);
    goObjects();
  } catch (e) { toast(e.message); }
};

$("#lightbox").onclick = () => $("#lightbox").classList.add("hidden");
$("#brand-home").onclick = () => goObjects();

/* ---------- старт ---------- */
async function enterApp() {
  $("#login-screen").classList.add("hidden");
  $("#app-screen").classList.remove("hidden");
  applyLevels();
  state.meta = await api("/api/meta");
  await goObjects();
}

(async function boot() {
  if (!state.token) return;
  try {
    state.user = await api("/api/me");
    enterApp();
  } catch (e) { doLogout(false); }
})();
