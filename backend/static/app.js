// Minimal vanilla-JS frontend. No build step. Talks to the FastAPI backend.
// When Node is installed we can replace this with the Vite + React SPA; the
// API contract stays identical.

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );

$("analyzeBtn").addEventListener("click", analyze);

async function analyze() {
  const btn = $("analyzeBtn");
  const status = $("status");
  const file = $("file").files[0];
  const sheetUrl = $("sheetUrl").value.trim();
  const keyCols = $("keyCols").value.trim();

  if (!file && !sheetUrl) {
    status.textContent = "Choose a CSV file or paste a Sheet URL.";
    return;
  }

  btn.disabled = true;
  status.textContent = "Analyzing…";
  try {
    const form = new FormData();
    if (keyCols) form.append("key_columns", keyCols);
    let url;
    if (file) {
      form.append("file", file);
      url = "/api/analyze/csv";
    } else {
      form.append("url", sheetUrl);
      url = "/api/analyze/sheet";
    }
    const res = await fetch(url, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");
    render(data);
    status.textContent = "";
  } catch (e) {
    status.innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}

function severityCounts(issues) {
  const c = { error: 0, warning: 0, info: 0 };
  issues.forEach((i) => (c[i.severity] = (c[i.severity] || 0) + 1));
  return c;
}

function render(d) {
  const c = severityCounts(d.issues);
  const reviewGroups = d.duplicate_groups.filter((g) => g.discards_data).length;

  const profileRows = d.profiles
    .map(
      (p) => `<tr>
        <td><code>${esc(p.name)}</code></td>
        <td>${esc(p.inferred_type)}</td>
        <td>${(p.fill_rate * 100).toFixed(0)}%</td>
        <td>${p.unique_count}</td>
        <td>${esc(p.sample_values.slice(0, 3).join(", "))}</td>
      </tr>`
    )
    .join("");

  const issueRows = d.issues
    .slice(0, 200)
    .map(
      (i) => `<tr>
        <td><span class="pill ${i.severity}">${i.severity}</span></td>
        <td>${esc(i.check)}</td>
        <td>${i.column ? esc(i.column) : ""}${i.row != null ? " · row " + i.row : ""}</td>
        <td>${esc(i.message)}</td>
      </tr>`
    )
    .join("");

  const dupRows = d.duplicate_groups
    .map((g, n) => {
      const tag = g.discards_data ? '<span class="review">review</span>' : "ok";
      const conflicts = g.conflicts
        .slice(0, 3)
        .map(
          (x) =>
            `keep '${esc(x.winner_value)}' / drop '${esc(x.losing_value)}' in ${esc(x.column)}`
        )
        .join("; ");
      return `<tr>
        <td>${n + 1}</td>
        <td>${tag}</td>
        <td>rows ${esc(g.row_indices.join(", "))}</td>
        <td>keep ${g.winner_index}</td>
        <td>${esc(conflicts)}</td>
      </tr>`;
    })
    .join("");

  $("results").classList.remove("hidden");
  $("results").innerHTML = `
    <div class="card">
      <div class="stats">
        <div><div class="stat">${d.row_count}</div><div class="muted">rows</div></div>
        <div><div class="stat">${d.column_count}</div><div class="muted">columns</div></div>
        <div><div class="stat">${c.error}</div><div class="muted">errors</div></div>
        <div><div class="stat">${c.warning}</div><div class="muted">warnings</div></div>
        <div><div class="stat">${d.duplicate_groups.length}</div><div class="muted">dup groups (${reviewGroups} need review)</div></div>
      </div>
      <div class="dl">
        <a class="btnlink" href="/api/jobs/${d.job_id}/readme"><button class="secondary">Download README.md</button></a>
        <a class="btnlink" href="/api/jobs/${d.job_id}/cleaned"><button class="secondary">Download cleaned.csv</button></a>
      </div>
    </div>

    <div class="card">
      <h3>Column data dictionary</h3>
      <table><thead><tr><th>Column</th><th>Type</th><th>Fill</th><th>Unique</th><th>Samples</th></tr></thead>
      <tbody>${profileRows}</tbody></table>
    </div>

    <div class="card">
      <h3>Quality findings (${d.issues.length})</h3>
      ${
        d.issues.length
          ? `<table><thead><tr><th>Severity</th><th>Check</th><th>Location</th><th>Message</th></tr></thead><tbody>${issueRows}</tbody></table>`
          : '<div class="muted">No issues found. 🎉</div>'
      }
    </div>

    <div class="card">
      <h3>Duplicates &amp; merge plan (${d.duplicate_groups.length})</h3>
      ${
        d.duplicate_groups.length
          ? `<p class="muted">Most-complete row is kept. Groups marked <span class="review">review</span> would discard a conflicting value — confirm before merging destructively.</p>
             <table><thead><tr><th>#</th><th>Status</th><th>Rows</th><th>Keep</th><th>Conflicts</th></tr></thead><tbody>${dupRows}</tbody></table>`
          : '<div class="muted">No duplicates detected.</div>'
      }
    </div>

    <div class="card" id="dcCard">
      <h3>Export to Dublin Core XML</h3>
      <p class="muted">Match each column to a Dublin Core field (or leave it as
        <em>— skip —</em>), choose which column names each file, then export one
        XML file per row as a ZIP.</p>
      <div id="dcMapping" class="muted">Loading columns…</div>
    </div>

    <div class="card" id="manifestCard">
      <h3>Export draft Merritt manifest</h3>
      <p class="muted">Pick which column feeds each manifest field, then export a
        UTF-8 CSV with one row per object. If a cell has several values separated
        by <code>|</code>, only the first is used.</p>
      <div id="manifestMapping" class="muted">Loading columns…</div>
    </div>
  `;

  loadDcMapping(d.job_id);
  loadManifestMapping(d.job_id);
}

// ---- Dublin Core export -----------------------------------------------------

let DC_JOB_ID = null;

async function loadDcMapping(jobId) {
  DC_JOB_ID = jobId;
  try {
    const res = await fetch(`/api/jobs/${jobId}/dc-mapping`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load columns");
    renderDcMapping(data);
  } catch (e) {
    $("dcMapping").innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  }
}

function renderDcMapping(data) {
  const { columns, elements, suggestion } = data;
  const options = (selected) =>
    [`<option value="">— skip —</option>`]
      .concat(
        elements.map(
          (el) =>
            `<option value="${esc(el)}"${el === selected ? " selected" : ""}>${esc(el)}</option>`
        )
      )
      .join("");

  const rows = columns
    .map(
      (col) => `<tr>
        <td><code>${esc(col)}</code></td>
        <td><select class="dcSel" data-col="${esc(col)}">${options(suggestion[col] || "")}</select></td>
      </tr>`
    )
    .join("");

  const fileOptions = columns
    .map((col) => `<option value="${esc(col)}">${esc(col)}</option>`)
    .join("");

  $("dcMapping").innerHTML = `
    <table style="margin-bottom:16px">
      <thead><tr><th>Spreadsheet column</th><th>Dublin Core field</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="row" style="align-items:flex-end">
      <div style="max-width:320px">
        <label>Which column should name each XML file?</label>
        <select id="dcFilename" style="width:100%;padding:8px 10px;border-radius:6px;border:1px solid var(--border);background:#fff">${fileOptions}</select>
      </div>
    </div>
    <div style="margin-top:16px">
      <button id="dcExportBtn">Export XML (ZIP)</button>
      <span id="dcStatus" class="muted"></span>
    </div>
  `;

  $("dcExportBtn").addEventListener("click", exportDc);
}

async function exportDc() {
  const btn = $("dcExportBtn");
  const status = $("dcStatus");
  const mapping = {};
  document.querySelectorAll(".dcSel").forEach((sel) => {
    mapping[sel.getAttribute("data-col")] = sel.value;
  });
  const anyMapped = Object.values(mapping).some((v) => v);
  if (!anyMapped) {
    status.innerHTML = `<span class="err-box">Map at least one column to a Dublin Core field first.</span>`;
    return;
  }
  const filenameColumn = $("dcFilename").value;

  btn.disabled = true;
  status.textContent = "Building XML files…";
  try {
    const form = new FormData();
    form.append("mapping", JSON.stringify(mapping));
    form.append("filename_column", filenameColumn);
    form.append("split_values", "true");
    const res = await fetch(`/api/jobs/${DC_JOB_ID}/dc-export`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Export failed");
    }
    // trigger the ZIP download
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "dublin_core_xml.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    // show a short summary from the response header
    let msg = "Done — your ZIP is downloading.";
    try {
      const raw = res.headers.get("X-Export-Summary");
      if (raw) {
        const s = JSON.parse(decodeURIComponent(raw));
        const extras = [];
        if (s.blank_filenames) extras.push(`${s.blank_filenames} row(s) had no filename value (named row-N)`);
        if (s.renamed_collisions) extras.push(`${s.renamed_collisions} duplicate name(s) renamed`);
        if (s.skipped_empty_rows) extras.push(`${s.skipped_empty_rows} empty row(s) skipped`);
        msg = `Done — ${s.file_count} XML file(s) in the ZIP.` + (extras.length ? " " + extras.join("; ") + "." : "");
      }
    } catch (_) {}
    status.textContent = msg;
  } catch (e) {
    status.innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}

// ---- Merritt manifest export ------------------------------------------------

let MANIFEST_JOB_ID = null;

async function loadManifestMapping(jobId) {
  MANIFEST_JOB_ID = jobId;
  try {
    const res = await fetch(`/api/jobs/${jobId}/manifest-mapping`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load columns");
    renderManifestMapping(data);
  } catch (e) {
    $("manifestMapping").innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  }
}

function renderManifestMapping(data) {
  const { columns, fields, suggestion } = data;
  const colOptions = (selected) =>
    [`<option value="">— none —</option>`]
      .concat(
        columns.map(
          (col) =>
            `<option value="${esc(col)}"${col === selected ? " selected" : ""}>${esc(col)}</option>`
        )
      )
      .join("");

  const rows = fields
    .map(
      (f) => `<tr>
        <td>${esc(f.label)}<br><code>${esc(f.header)}</code></td>
        <td><select class="mfSel" data-key="${esc(f.key)}">${colOptions(suggestion[f.key] || "")}</select></td>
      </tr>`
    )
    .join("");

  $("manifestMapping").innerHTML = `
    <table style="margin-bottom:16px;max-width:620px">
      <thead><tr><th>Manifest field</th><th>Spreadsheet column</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div>
      <button id="manifestExportBtn">Export Merritt manifest (CSV)</button>
      <span id="manifestStatus" class="muted"></span>
    </div>
  `;

  $("manifestExportBtn").addEventListener("click", exportManifest);
}

async function exportManifest() {
  const btn = $("manifestExportBtn");
  const status = $("manifestStatus");
  const mapping = {};
  document.querySelectorAll(".mfSel").forEach((sel) => {
    mapping[sel.getAttribute("data-key")] = sel.value;
  });
  if (!Object.values(mapping).some((v) => v)) {
    status.innerHTML = `<span class="err-box">Pick a column for at least one manifest field first.</span>`;
    return;
  }

  btn.disabled = true;
  status.textContent = "Building manifest…";
  try {
    const form = new FormData();
    form.append("mapping", JSON.stringify(mapping));
    const res = await fetch(`/api/jobs/${MANIFEST_JOB_ID}/manifest-export`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Export failed");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "merritt_manifest.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    let msg = "Done — your manifest is downloading.";
    try {
      const raw = res.headers.get("X-Export-Summary");
      if (raw) {
        const s = JSON.parse(decodeURIComponent(raw));
        msg = `Done — ${s.row_count} object row(s) in the manifest.`;
        if (s.skipped_empty_rows) msg += ` ${s.skipped_empty_rows} empty row(s) skipped.`;
      }
    } catch (_) {}
    status.textContent = msg;
  } catch (e) {
    status.innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}
