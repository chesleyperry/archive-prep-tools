// Frontend for the spreadsheet-merge tool. No build step. Talks to /api/merge.

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );

$("mergeBtn").addEventListener("click", doMerge);

async function doMerge() {
  const btn = $("mergeBtn");
  const status = $("status");
  const master = $("master").files[0];
  const addition = $("addition").files[0];
  const keyCols = $("keyCols").value.trim();

  if (!master || !addition) {
    status.textContent = "Choose both a master file and a new file.";
    return;
  }
  if (!keyCols) {
    status.textContent = "Name at least one key column to match rows on.";
    return;
  }

  btn.disabled = true;
  status.textContent = "Merging…";
  try {
    const form = new FormData();
    form.append("master", master);
    form.append("addition", addition);
    form.append("key_columns", keyCols);
    const res = await fetch("/api/merge/csv", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Merge failed");
    render(data);
    status.textContent = "";
  } catch (e) {
    status.innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}

function keyStr(key) {
  return Object.entries(key)
    .map(([k, v]) => `${esc(k)}=${esc(v)}`)
    .join(", ");
}

function render(d) {
  const warnings = d.warnings.length
    ? `<div class="warn-box">${d.warnings.map(esc).join("<br>")}</div>`
    : "";

  const changeRows = d.changes
    .map(
      (c) => `<tr>
        <td>${keyStr(c.key)}</td>
        <td><code>${esc(c.column)}</code></td>
        <td>${c.reason === "filled_blank" ? '<span class="muted">(blank)</span>' : esc(c.old_value)}</td>
        <td>${esc(c.new_value)}</td>
        <td>${c.reason === "filled_blank" ? "filled blank" : "longer wins"}</td>
      </tr>`
    )
    .join("");

  const keptRows = d.kept_differences
    .map(
      (k) => `<tr>
        <td>${keyStr(k.key)}</td>
        <td><code>${esc(k.column)}</code></td>
        <td>${esc(k.master_value)}</td>
        <td>${esc(k.new_value)}</td>
      </tr>`
    )
    .join("");

  $("results").classList.remove("hidden");
  $("results").innerHTML = `
    ${warnings}
    <div class="card">
      <div class="stats">
        <div><div class="stat">${d.merged_row_count}</div><div class="muted">rows in merged master (was ${d.master_row_count})</div></div>
        <div><div class="stat">${d.rows_added}</div><div class="muted">new rows added</div></div>
        <div><div class="stat">${d.cells_filled}</div><div class="muted">blanks filled</div></div>
        <div><div class="stat">${d.cells_updated}</div><div class="muted">cells updated (more detail)</div></div>
        <div><div class="stat">${d.columns_added.length}</div><div class="muted">columns added</div></div>
        <div><div class="stat">${d.differences_kept}</div><div class="muted">differences to review</div></div>
      </div>
      <div class="dl">
        <a class="btnlink" href="/api/merge/${d.job_id}/result"><button>Download merged master CSV</button></a>
        <a class="btnlink" href="/api/merge/${d.job_id}/report"><button class="secondary">Download change report</button></a>
      </div>
      ${d.columns_added.length ? `<p class="muted" style="margin-top:12px">New columns added: ${d.columns_added.map(esc).join(", ")}</p>` : ""}
    </div>

    <div class="card">
      <h3>Changes applied (${d.changes.length})</h3>
      ${
        d.changes.length
          ? `<table><thead><tr><th>Row key</th><th>Column</th><th>Was</th><th>Now</th><th>Why</th></tr></thead><tbody>${changeRows}</tbody></table>`
          : '<div class="muted">No existing cells were changed.</div>'
      }
    </div>

    <div class="card">
      <h3>Differences kept — please review (${d.kept_differences.length})</h3>
      ${
        d.kept_differences.length
          ? `<p class="muted">Both sheets had a value here and they differ, but the new value wasn't longer, so the master was kept. Check whether the new value is actually better.</p>
             <table><thead><tr><th>Row key</th><th>Column</th><th>Master kept</th><th>New (ignored)</th></tr></thead><tbody>${keptRows}</tbody></table>`
          : '<div class="muted">No unresolved disagreements. 🎉</div>'
      }
    </div>
  `;
}
