// api.js — único arquivo que fala com o ACS API
// Nenhum outro arquivo faz fetch diretamente.

// URL relativa — funciona com localhost, 127.0.0.1 ou qualquer host que sirva o frontend
const API = "";

// Mapa: performance → steps
const PERF_STEPS = { fast: 4, balanced: 8, pro: 20 };

export async function uploadRefImage(file) {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`${API}/upload-ref`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`Upload HTTP ${r.status}`);
  const d = await r.json();
  return d.path; // caminho no servidor
}

export async function checkHealth() {
  const r = await fetch(`${API}/health`);
  return r.json();
}

export async function startGeneration({ prompt, negative, model, resolution, performance, steps, seed, injectImages, controlMode, refImagePath, ctrlImagePath, loras_choices, loras_multipliers, promptEnhancer }) {
  const resolvedSteps = steps || PERF_STEPS[performance] || 4;

  const payload = {
    prompt,
    negative_prompt:  negative     || "",
    model:            model        || "Flux Balanced",
    resolution:       resolution   || "1024x1024",
    steps:            resolvedSteps,
    seed:             seed ?? -1,
    generation_mode:  "t2i",                    // Fix: aba Image sempre usa t2i, não o default t2v
    inject_video_prompt_type: injectImages      || "",
    ctrl_video_prompt_type:   controlMode       || "",
    ref_image_path:           refImagePath      || "",
    ref_inject_paths:         refImagePath ? [refImagePath] : [],
    ctrl_image_path:          ctrlImagePath     || "",
    loras_choices:            loras_choices     || [],
    loras_multipliers:        loras_multipliers || "",
    prompt_enhancer:          promptEnhancer    ?? "",  // A3: "" = OFF, "T" = ON (sobrescreve default "T" do backend)
  };

  const r = await fetch(`${API}/generate`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const e = await r.json();
      const d = e.detail;
      if (d) msg = (typeof d === 'string') ? d : (d.message || d.error || JSON.stringify(d));
    } catch (_) {}
    throw new Error(msg);
  }
  return r.json(); // { job_id, status }
}

export async function pollStatus(jobId) {
  const r = await fetch(`${API}/status/${jobId}`);
  if (r.status === 404) return { status: "not_found" }; // job sumiu do servidor (restart?)
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json(); // { status, step, progress, output, error }
}

export async function loadOutputs() {
  const r = await fetch(`${API}/outputs`);
  if (!r.ok) return [];
  const d = await r.json();
  return (d.outputs || []).filter(o => o.type === "image");
}

export function fileUrl(url) {
  return `${API}${url}`;
}
