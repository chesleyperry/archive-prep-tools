// Minimal vanilla-JS control panel for AV File Access Preparation.
// Starts a batch job, polls progress, and renders per-file results.

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );

let pollTimer = null;
let currentJob = null;

$("startBtn").addEventListener("click", start);
$("cancelBtn").addEventListener("click", cancel);

async function start() {
  const inputDir = $("inputDir").value.trim();
  const outputDir = $("outputDir").value.trim();
  const status = $("status");
  if (!inputDir || !outputDir) {
    status.innerHTML = '<span class="err-box">Input and output directories are required.</span>';
    return;
  }

  const form = new FormData();
  form.append("input_dir", inputDir);
  form.append("output_dir", outputDir);
  form.append("id_column", $("idColumn").value.trim() || "localIdentifier");
  form.append("whisper_model", $("whisperModel").value);
  form.append("enrich_model", $("enrichModel").value.trim() || "qwen2.5:latest");
  const csv = $("csv").files[0];
  if (csv) form.append("file", csv);

  $("startBtn").disabled = true;
  status.textContent = "Starting…";
  try {
    const res = await fetch("/api/av/batch", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");
    currentJob = data.job_id;
    $("cancelBtn").classList.remove("hidden");
    poll();
  } catch (e) {
    status.innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
    $("startBtn").disabled = false;
  }
}

async function cancel() {
  if (!currentJob) return;
  await fetch(`/api/av/batch/${currentJob}/cancel`, { method: "POST" });
  $("status").textContent = "Cancelling…";
}

function poll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(tick, 0);
}

async function tick() {
  try {
    const res = await fetch(`/api/av/batch/${currentJob}`);
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || "Lost the job");
    render(d);
    if (["running", "queued"].includes(d.status)) {
      pollTimer = setTimeout(tick, 1500);
    } else {
      finish(d);
    }
  } catch (e) {
    $("status").innerHTML = `<span class="err-box">${esc(e.message)}</span>`;
    $("startBtn").disabled = false;
  }
}

function finish(d) {
  $("startBtn").disabled = false;
  $("cancelBtn").classList.add("hidden");
  const label = { done: "Done.", cancelled: "Cancelled.", error: "Failed." }[d.status] || "";
  $("status").textContent = d.error ? `${label} ${d.error}` : label;
}

const STATUS_PILL = (s) => {
  if (s === "transcribed") return "transcribed";
  if (s === "error") return "error";
  if (s && s.startsWith("partial")) return "skip";
  return "info";
};

function render(d) {
  const pct = d.total ? Math.round((d.completed / d.total) * 100) : 0;
  const rows = (d.results || [])
    .map((r) => {
      const e = r.enrichment || {};
      const ents = ["persons", "places", "music_titles", "poem_titles", "book_titles"]
        .map((k) => (e[k] && e[k].length ? `${k.split("_")[0]}: ${e[k].join(", ")}` : ""))
        .filter(Boolean)
        .join(" · ");
      return `<tr>
        <td><code>${esc(r.local_identifier)}</code></td>
        <td><span class="pill ${STATUS_PILL(r.status)}">${esc(r.status)}</span></td>
        <td>${esc(e.suggested_title || "")}${e.suggested_date ? " · " + esc(e.suggested_date) : ""}</td>
        <td>${esc(e.content_description || "")}<div class="muted">${esc(ents)}</div></td>
        <td>${(r.outputs || []).map((o) => `<div class="muted">${esc(o.split("/").pop())}</div>`).join("")}</td>
      </tr>`;
    })
    .join("");

  const dl = d.csv_filename
    ? `<div class="dl"><a class="btnlink" href="/api/av/batch/${d.job_id}/csv"><button class="secondary">Download ${esc(d.csv_filename)}</button></a></div>`
    : "";

  $("results").classList.remove("hidden");
  $("results").innerHTML = `
    <div class="card">
      <div class="muted">${d.completed} / ${d.total} files — ${esc(d.status)}${d.current ? " · " + esc(d.current) : ""}</div>
      <div class="bar" style="margin:10px 0"><div style="width:${pct}%"></div></div>
      ${dl}
    </div>
    <div class="card">
      <h3>Files</h3>
      <table>
        <thead><tr><th>ID</th><th>Status</th><th>Suggested</th><th>Description &amp; entities</th><th>Outputs</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
