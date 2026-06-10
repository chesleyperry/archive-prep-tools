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
  `;
}
