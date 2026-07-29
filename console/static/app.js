(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  let configSchema = [];
  let configValues = {};
  let folders = [];
  let jobs = [];
  let jobCat = "all";
  let logOffset = 0;
  let pollTimer = null;

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
    return data;
  }

  function showMsg(el, text, isErr = false) {
    el.hidden = false;
    el.textContent = text;
    el.classList.toggle("err", !!isErr);
  }

  // Tabs
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab").forEach((b) => b.classList.remove("active"));
      $$(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`#tab-${btn.dataset.tab}`).classList.add("active");
    });
  });

  async function refreshStatus() {
    const s = await api("/api/status");
    const chips = $("#statusChips");
    const v = s.validation || {};
    chips.innerHTML = `
      <span class="pill">分支 <strong>${esc(s.branch)}</strong></span>
      <span class="pill">WORKER <strong>${esc(s.worker_id || "-")}</strong></span>
      <span class="pill ${v.ok ? "ok" : "bad"}">${v.ok ? "配置 OK" : "配置缺项"}</span>
    `;
    const job = (s.job && s.job.job) || null;
    const badge = $("#jobBadge");
    if (!job) {
      badge.textContent = "空闲";
      badge.className = "badge";
      $("#btnStop").disabled = true;
    } else {
      badge.textContent = `${job.status} · ${job.title}`;
      badge.className = `badge ${job.status}`;
      $("#btnStop").disabled = job.status !== "running";
    }
    return s;
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  // Jobs
  async function loadJobs() {
    const data = await api("/api/jobs/catalog");
    jobs = data.jobs || [];
    renderJobs();
  }

  function renderJobs() {
    const list = $("#jobList");
    const filtered = jobs.filter((j) => jobCat === "all" || j.category === jobCat);
    list.innerHTML = filtered
      .map(
        (j) => `
      <button class="job-item" data-id="${esc(j.id)}" data-needs="${j.needs_folder ? "1" : "0"}">
        <span class="t">${esc(j.title)}</span>
        <span class="d">${esc(j.description || j.category)}</span>
      </button>`
      )
      .join("");
    list.querySelectorAll(".job-item").forEach((btn) => {
      btn.addEventListener("click", () => startJob(btn.dataset.id, btn.dataset.needs === "1"));
    });
  }

  $$(".job-filters .chip").forEach((c) => {
    c.addEventListener("click", () => {
      $$(".job-filters .chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      jobCat = c.dataset.cat;
      renderJobs();
    });
  });

  async function startJob(jobId, needsFolder) {
    const folderId = $("#folderSelect").value || null;
    if (needsFolder && !folderId) {
      alert("请先在下方选择 folder id");
      return;
    }
    try {
      $("#logView").textContent = "";
      logOffset = 0;
      await api("/api/jobs/start", {
        method: "POST",
        body: JSON.stringify({
          job_id: jobId,
          folder_id: needsFolder ? folderId : folderId || undefined,
        }),
      });
      await refreshStatus();
      startPolling();
    } catch (e) {
      alert(e.message);
    }
  }

  $("#btnStop").addEventListener("click", async () => {
    await api("/api/jobs/stop", { method: "POST", body: "{}" });
    await refreshStatus();
  });
  $("#btnRefreshStatus").addEventListener("click", () => refreshStatus());

  async function pollLogs() {
    const data = await api(`/api/jobs/logs?offset=${logOffset}`);
    if (data.lines && data.lines.length) {
      $("#logView").textContent += data.lines.join("");
      logOffset = data.offset;
      const pre = $("#logView");
      pre.scrollTop = pre.scrollHeight;
    }
    await refreshStatus();
    if (data.status && data.status !== "running") {
      stopPolling();
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(pollLogs, 800);
    pollLogs();
  }
  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  // Config
  async function loadConfig() {
    const reveal = $("#revealSecrets").checked;
    const data = await api(`/api/config?reveal=${reveal ? "true" : "false"}`);
    configSchema = data.schema || [];
    configValues = data.values || {};
    $("#envPathHint").textContent = data.path + (data.exists ? "" : "（文件尚不存在，保存时会创建）");
    renderConfig();
  }

  function renderConfig() {
    const groups = {};
    for (const item of configSchema) {
      (groups[item.group] ||= { label: item.group_label, fields: [] }).fields.push(item);
    }
    const form = $("#configForm");
    form.innerHTML = Object.entries(groups)
      .map(([gid, g]) => {
        const fields = g.fields
          .map((f) => {
            const val = configValues[f.key] ?? "";
            if (f.type === "bool") {
              const on = String(val).toLowerCase() === "true";
              return `<div class="field"><label>${esc(f.label)}</label>
                <div class="bool"><input type="checkbox" data-key="${esc(f.key)}" ${on ? "checked" : ""}/> 开启</div></div>`;
            }
            const inputType = f.secret ? "password" : f.type === "int" || f.type === "float" ? "number" : "text";
            const step = f.type === "float" ? ' step="any"' : f.type === "int" ? ' step="1"' : "";
            return `<div class="field"><label for="cfg-${esc(f.key)}">${esc(f.label)}</label>
              <input id="cfg-${esc(f.key)}" data-key="${esc(f.key)}" type="${inputType}"${step} value="${esc(val)}" /></div>`;
          })
          .join("");
        return `<div class="group" data-group="${esc(gid)}"><h3>${esc(g.label)}</h3><div class="fields">${fields}</div></div>`;
      })
      .join("");
  }

  function collectConfig() {
    const out = {};
    $$("#configForm [data-key]").forEach((el) => {
      if (el.type === "checkbox") out[el.dataset.key] = el.checked ? "true" : "false";
      else out[el.dataset.key] = el.value;
    });
    return out;
  }

  $("#btnReloadConfig").addEventListener("click", () => loadConfig().catch((e) => alert(e.message)));
  $("#revealSecrets").addEventListener("change", () => loadConfig().catch((e) => alert(e.message)));
  $("#btnSaveConfig").addEventListener("click", async () => {
    try {
      const res = await api("/api/config", {
        method: "PUT",
        body: JSON.stringify({ values: collectConfig() }),
      });
      showMsg($("#configMsg"), res.note || "已保存", !res.validation?.ok);
      await refreshStatus();
      await loadConfig();
    } catch (e) {
      showMsg($("#configMsg"), e.message, true);
    }
  });

  // Folders
  async function loadFolders() {
    const data = await api("/api/folders");
    folders = data.folders || [];
    $("#foldersPathHint").textContent = data.path;
    $("#foldersNotes").value = data.notes || "";
    renderFolders();
    fillFolderSelect();
  }

  function renderFolders() {
    const tb = $("#foldersTable tbody");
    tb.innerHTML = folders
      .map((f, i) => {
        return `<tr data-i="${i}">
          <td><input type="checkbox" data-f="enabled" ${f.enabled ? "checked" : ""} /></td>
          <td><input type="text" data-f="id" value="${esc(f.id || "")}" /></td>
          <td><input type="text" data-f="name" value="${esc(f.name || "")}" /></td>
          <td><input type="text" data-f="assignee" value="${esc(f.assignee || "")}" list="assignees" /></td>
          <td><input type="number" data-f="priority" value="${esc(f.priority ?? 0)}" style="width:5rem" /></td>
          <td><input class="token" type="text" data-f="token" value="${esc(f.token || "")}" /></td>
        </tr>`;
      })
      .join("");
    if (!$("#assignees")) {
      const dl = document.createElement("datalist");
      dl.id = "assignees";
      dl.innerHTML = ["Hydrew", "Jamie", "Hayes"].map((n) => `<option value="${n}">`).join("");
      document.body.appendChild(dl);
    }
  }

  function collectFolders() {
    return [...$("#foldersTable tbody").querySelectorAll("tr")].map((tr) => {
      const get = (name) => tr.querySelector(`[data-f="${name}"]`);
      return {
        enabled: get("enabled").checked,
        id: get("id").value.trim(),
        name: get("name").value.trim(),
        assignee: get("assignee").value.trim(),
        priority: Number(get("priority").value || 0),
        token: get("token").value.trim(),
      };
    });
  }

  function fillFolderSelect() {
    const sel = $("#folderSelect");
    const cur = sel.value;
    sel.innerHTML =
      `<option value="">（不指定）</option>` +
      folders
        .map((f) => `<option value="${esc(f.id)}">${esc(f.id)} · ${esc(f.assignee || "-")}</option>`)
        .join("");
    if (cur) sel.value = cur;
  }

  $("#btnReloadFolders").addEventListener("click", () => loadFolders().catch((e) => alert(e.message)));
  $("#btnSaveFolders").addEventListener("click", async () => {
    try {
      const res = await api("/api/folders", {
        method: "PUT",
        body: JSON.stringify({
          notes: $("#foldersNotes").value,
          folders: collectFolders(),
        }),
      });
      showMsg($("#foldersMsg"), `已保存 ${res.count} 个文件夹 → ${res.path}`);
      await loadFolders();
    } catch (e) {
      showMsg($("#foldersMsg"), e.message, true);
    }
  });

  async function boot() {
    await Promise.all([refreshStatus(), loadJobs(), loadConfig(), loadFolders()]);
    const s = await refreshStatus();
    if (s.job?.running) startPolling();
  }

  boot().catch((e) => {
    console.error(e);
    alert("控制台初始化失败: " + e.message);
  });
})();
