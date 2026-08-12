(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  let configSchema = [];
  let configValues = {};
  let folders = [];
  let jobs = [];
  let jobCategories = [];
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
    if (!el) return;
    el.hidden = false;
    el.textContent = text;
    el.classList.toggle("err", !!isErr);
    try {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (_) {
      /* ignore */
    }
  }

  function setBusy(btn, busy, labelWhenBusy) {
    if (!btn) return;
    if (busy) {
      btn.dataset.prevText = btn.textContent;
      btn.disabled = true;
      if (labelWhenBusy) btn.textContent = labelWhenBusy;
    } else {
      btn.disabled = false;
      if (btn.dataset.prevText) btn.textContent = btn.dataset.prevText;
    }
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
  const CATEGORY_FALLBACK = [
    {
      id: "core",
      label: "主流程",
      hint: "日常点「增量更新」；只有要强制重扫源目录时才点「全量重扫」",
    },
    { id: "enrich", label: "副本增强", hint: "只处理 TARGET 已复制文档" },
    { id: "bitable_meta", label: "文档元数据表", hint: "文档元数据 → 飞书多维表格" },
    { id: "bitable_title", label: "归纳新标题", hint: "多维表格或重命名 TARGET 副本（不改源）" },
    { id: "ops", label: "运维纠偏", hint: "Others / 附件重试" },
  ];

  async function loadJobs() {
    const data = await api("/api/jobs/catalog");
    jobs = data.jobs || [];
    jobCategories = data.categories && data.categories.length ? data.categories : CATEGORY_FALLBACK;
    renderJobs();
  }

  function jobBadges(j) {
    const tags = [];
    if (j.force_rescan) tags.push('<span class="tag tag-danger">全量重扫</span>');
    else if (j.category === "core" && String(j.id || "").startsWith("classify")) {
      tags.push('<span class="tag tag-target">增量更新</span>');
    }
    if (j.scope === "target") tags.push('<span class="tag tag-target">TARGET</span>');
    if (j.scope === "scan") tags.push('<span class="tag tag-scan">扫源</span>');
    if (j.dry_run) tags.push('<span class="tag tag-dry">试跑</span>');
    if (j.danger && !j.force_rescan) tags.push('<span class="tag tag-danger">慎用</span>');
    if (j.needs_folder) tags.push('<span class="tag tag-folder">需选 folder</span>');
    return tags.join("");
  }

  function renderJobButton(j) {
    const cls = ["job-item"];
    if (j.dry_run) cls.push("dry");
    if (j.danger) cls.push("danger-job");
    return `
      <button class="${cls.join(" ")}" data-id="${esc(j.id)}" data-needs="${j.needs_folder ? "1" : "0"}">
        <span class="t-row"><span class="t">${esc(j.title)}</span><span class="tags">${jobBadges(j)}</span></span>
        <span class="d">${esc(j.description || j.category)}</span>
      </button>`;
  }

  function sortJobsInGroup(list) {
    // formal first, dry_run last; needs_folder near end of formal; keep relative order otherwise
    return [...list].sort((a, b) => {
      const score = (j) =>
        (j.dry_run ? 4 : 0) + (j.needs_folder ? 2 : 0) + (j.danger && !j.force_rescan ? 1 : 0);
      return score(a) - score(b);
    });
  }

  function renderJobs() {
    const list = $("#jobList");
    const cats = jobCategories.length ? jobCategories : CATEGORY_FALLBACK;
    const visibleCats =
      jobCat === "all" ? cats : cats.filter((c) => c.id === jobCat);

    const html = visibleCats
      .map((cat) => {
        const groupJobs = sortJobsInGroup(
          jobs.filter((j) => j.category === cat.id)
        );
        if (!groupJobs.length) return "";
        return `
          <section class="job-group" data-cat="${esc(cat.id)}">
            <header class="job-group-head">
              <h3>${esc(cat.label)}</h3>
              <p>${esc(cat.hint || "")}</p>
            </header>
            <div class="job-group-body">
              ${groupJobs.map(renderJobButton).join("")}
            </div>
          </section>`;
      })
      .join("");

    list.innerHTML = html || '<p class="hint">该分组暂无任务</p>';
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
    if (typeof data.offset === "number") {
      logOffset = data.offset;
    }
    if (data.lines && data.lines.length) {
      $("#logView").textContent += data.lines.join("");
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

  $("#btnReloadConfig").addEventListener("click", async () => {
    const btn = $("#btnReloadConfig");
    setBusy(btn, true, "加载中…");
    try {
      await loadConfig();
      showMsg($("#configMsg"), "已从磁盘重新加载 .env", false);
    } catch (e) {
      showMsg($("#configMsg"), e.message, true);
      alert(e.message);
    } finally {
      setBusy(btn, false);
    }
  });
  $("#revealSecrets").addEventListener("change", () => loadConfig().catch((e) => alert(e.message)));
  $("#btnSaveConfig").addEventListener("click", async () => {
    const btn = $("#btnSaveConfig");
    setBusy(btn, true, "保存中…");
    try {
      const res = await api("/api/config", {
        method: "PUT",
        body: JSON.stringify({ values: collectConfig() }),
      });
      const v = res.validation || {};
      let text = res.note || "已保存";
      if (res.path) text += ` → ${res.path}`;
      if (v.ok === false && v.error) {
        text += `（校验告警：${v.error}）`;
      }
      // 已写入磁盘即成功；校验缺项只作告警，不要伪装成失败无反馈
      showMsg($("#configMsg"), text, false);
      if (v.ok === false) {
        $("#configMsg").classList.add("warn");
      } else {
        $("#configMsg").classList.remove("warn");
      }
      await refreshStatus();
      await loadConfig();
    } catch (e) {
      showMsg($("#configMsg"), "保存失败：" + e.message, true);
      alert("保存失败：" + e.message);
    } finally {
      setBusy(btn, false);
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
          <td><button type="button" class="btn-row-del" data-del="${i}">移除</button></td>
        </tr>`;
      })
      .join("");
    if (!$("#assignees")) {
      const dl = document.createElement("datalist");
      dl.id = "assignees";
      dl.innerHTML = ["Hydrew", "Jamie", "Hayes"].map((n) => `<option value="${n}">`).join("");
      document.body.appendChild(dl);
    }
    tb.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const i = Number(btn.getAttribute("data-del"));
        folders = collectFolders().filter((_, idx) => idx !== i);
        renderFolders();
        fillFolderSelect();
        showMsg($("#foldersMsg"), "已从表格移除一行，点「保存清单」才会写入文件", false);
      });
    });
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

  function normalizeToken(raw) {
    let t = (raw || "").trim();
    if (!t) return "";
    const wiki = t.match(/\/wiki\/([A-Za-z0-9_-]+)/i);
    if (wiki) return wiki[1];
    // bare token or trailing junk
    return t.split(/[/?#\s]/)[0].trim();
  }

  function collectAddPayload() {
    const priRaw = $("#addPriority").value.trim();
    return {
      token: normalizeToken($("#addToken").value),
      id: $("#addId").value.trim() || null,
      name: $("#addName").value.trim() || null,
      assignee: $("#addAssignee").value.trim() || null,
      priority: priRaw === "" ? null : Number(priRaw),
      enabled: $("#addEnabled").checked,
      resolve_wiki: true,
    };
  }

  function clearAddForm() {
    $("#addToken").value = "";
    $("#addId").value = "";
    $("#addName").value = "";
    $("#addPriority").value = "";
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

  $("#btnPreviewFolder").addEventListener("click", async () => {
    const btn = $("#btnPreviewFolder");
    try {
      setBusy(btn, true);
      const payload = collectAddPayload();
      if (!payload.token) throw new Error("请先填写 token");
      const res = await api("/api/folders/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const s = res.suggested || {};
      if (s.id) $("#addId").value = s.id;
      if (s.name) $("#addName").value = s.name;
      if (s.assignee && !$("#addAssignee").value.trim()) $("#addAssignee").value = s.assignee;
      if (s.priority != null && $("#addPriority").value.trim() === "") {
        $("#addPriority").value = String(s.priority);
      }
      let tip = `已解析：${s.name || s.id}`;
      if (res.wiki?.error) tip += `（飞书：${res.wiki.error}）`;
      if (res.duplicate_token) tip += ` · 警告：token 已存在于 ${res.duplicate_token}`;
      if (res.duplicate_id) tip += ` · 警告：id 冲突 ${res.duplicate_id}`;
      showMsg($("#addFolderMsg"), tip, !!(res.duplicate_token || res.duplicate_id));
    } catch (e) {
      showMsg($("#addFolderMsg"), e.message, true);
    } finally {
      setBusy(btn, false);
    }
  });

  $("#btnAddFolder").addEventListener("click", async () => {
    const btn = $("#btnAddFolder");
    try {
      setBusy(btn, true);
      const payload = collectAddPayload();
      if (!payload.token) throw new Error("请先填写 token");
      const res = await api("/api/folders/add", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const f = res.folder || {};
      showMsg(
        $("#addFolderMsg"),
        `已添加 ${f.id}（${f.name}）→ 共 ${res.count} 项 · ${res.path}`
      );
      clearAddForm();
      await loadFolders();
    } catch (e) {
      showMsg($("#addFolderMsg"), e.message, true);
    } finally {
      setBusy(btn, false);
    }
  });

  async function boot() {
    const [status] = await Promise.all([
      refreshStatus(),
      loadJobs(),
      loadConfig(),
      loadFolders(),
    ]);
    if (status?.worker_id && !$("#addAssignee").value.trim()) {
      $("#addAssignee").value = status.worker_id;
    }
    const s = await refreshStatus();
    if (s.job?.running) startPolling();
  }

  boot().catch((e) => {
    console.error(e);
    alert("控制台初始化失败: " + e.message);
  });
})();
