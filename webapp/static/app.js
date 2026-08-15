// Reality Capture Review UI -- talks to the Flask API in server.py,
// which in turn calls the same building_model/geometry/review
// functions the Python test suite already exercises. This file
// has no domain logic of its own; it only renders state and posts
// user actions.

const SVG_NS = "http://www.w3.org/2000/svg";
const PADDING_METERS = 1.0;

let currentModelData = null;
let drawingMode = false;
let drawStartPoint = null; // model-space [x, y], set after first click

const svgEl = document.getElementById("floorplan");
const bundlePathEl = document.getElementById("bundle-path");
const loadBtn = document.getElementById("load-btn");
const loadStatusEl = document.getElementById("load-status");
const drawWallBtn = document.getElementById("draw-wall-btn");
const reextractBtn = document.getElementById("reextract-btn");
const exportIfcBtn = document.getElementById("export-ifc-btn");
const drawHintEl = document.getElementById("draw-hint");
const remainingCountEl = document.getElementById("remaining-count");
const reviewItemEl = document.getElementById("review-item");
const validationErrorsEl = document.getElementById("validation-errors");

function confidenceBand(confidence) {
  if (confidence >= 0.9) return "high";
  if (confidence >= 0.7) return "med";
  return "low";
}

// --- Coordinate transform: model meters -> SVG pixel space ---

function computeTransform(data) {
  const xs = [];
  const ys = [];
  for (const w of data.walls) {
    for (const p of w.centerline) {
      xs.push(p[0]);
      ys.push(p[1]);
    }
  }
  for (const r of data.rooms) {
    for (const p of r.boundary) {
      xs.push(p[0]);
      ys.push(p[1]);
    }
  }
  if (xs.length === 0) {
    return { toSvg: (x, y) => [400, 300], scale: 1, minX: 0, minY: 0 };
  }

  const minX = Math.min(...xs) - PADDING_METERS;
  const maxX = Math.max(...xs) + PADDING_METERS;
  const minY = Math.min(...ys) - PADDING_METERS;
  const maxY = Math.max(...ys) + PADDING_METERS;

  const viewW = 800;
  const viewH = 600;
  const modelW = Math.max(maxX - minX, 0.1);
  const modelH = Math.max(maxY - minY, 0.1);
  const scale = Math.min(viewW / modelW, viewH / modelH);

  // flip Y so model "up" (+y) renders visually upward, not inverted
  const toSvg = (x, y) => [
    (x - minX) * scale,
    viewH - (y - minY) * scale,
  ];

  return { toSvg, scale, minX, minY, viewW, viewH };
}

function toModelSpace(transform, svgX, svgY) {
  const x = svgX / transform.scale + transform.minX;
  const y = (transform.viewH - svgY) / transform.scale + transform.minY;
  return [x, y];
}

// --- Rendering ---

function clearSvg() {
  while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
}

function renderFloorplan(data) {
  clearSvg();
  const transform = computeTransform(data);
  svgEl.dataset.minX = transform.minX;
  svgEl.dataset.minY = transform.minY;
  svgEl.dataset.scale = transform.scale;
  svgEl.dataset.viewH = transform.viewH;

  for (const room of data.rooms) {
    const points = room.boundary
      .map((p) => transform.toSvg(p[0], p[1]).join(","))
      .join(" ");
    const poly = document.createElementNS(SVG_NS, "polygon");
    poly.setAttribute("points", points);
    const band = confidenceBand(room.confidence);
    poly.setAttribute("class", `room-fill conf-${band}-fill conf-${band}-stroke`);
    poly.setAttribute("title", room.label);
    svgEl.appendChild(poly);
  }

  for (const wall of data.walls) {
    const [x1, y1] = transform.toSvg(wall.centerline[0][0], wall.centerline[0][1]);
    const [x2, y2] = transform.toSvg(wall.centerline[1][0], wall.centerline[1][1]);
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", x1);
    line.setAttribute("y1", y1);
    line.setAttribute("x2", x2);
    line.setAttribute("y2", y2);
    const band = confidenceBand(wall.confidence);
    line.setAttribute("class", `wall-line conf-${band}-stroke`);
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = wall.label;
    line.appendChild(title);
    svgEl.appendChild(line);
  }

  for (const door of data.doors) {
    const [x, y] = transform.toSvg(door.position[0], door.position[1]);
    const marker = document.createElementNS(SVG_NS, "circle");
    marker.setAttribute("cx", x);
    marker.setAttribute("cy", y);
    marker.setAttribute("r", 6);
    marker.setAttribute("class", "door-marker");
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = door.label;
    marker.appendChild(title);
    svgEl.appendChild(marker);
  }

  for (const win of data.windows) {
    const [x, y] = transform.toSvg(win.position[0], win.position[1]);
    const marker = document.createElementNS(SVG_NS, "rect");
    marker.setAttribute("x", x - 5);
    marker.setAttribute("y", y - 5);
    marker.setAttribute("width", 10);
    marker.setAttribute("height", 10);
    marker.setAttribute("class", "window-marker");
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = win.label;
    marker.appendChild(title);
    svgEl.appendChild(marker);
  }

  validationErrorsEl.textContent =
    data.validation_errors && data.validation_errors.length
      ? "Validation errors: " + data.validation_errors.join("; ")
      : "";
}

// --- Review panel ---

function renderReviewItem(item) {
  remainingCountEl.textContent = item
    ? `(${item.remaining_count} remaining)`
    : "";

  if (!item) {
    reviewItemEl.innerHTML = currentModelData
      ? "<p>All objects reviewed.</p>"
      : "<p id=\"review-empty\">No model loaded yet.</p>";
    return;
  }

  const fieldsHtml = fieldsForType(item.type);
  reviewItemEl.innerHTML = `
    <div class="review-label">${escapeHtml(item.display_text)}</div>
    ${fieldsHtml}
    <div class="action-row">
      <button id="approve-btn">Approve</button>
      ${item.type !== "room" ? '<button id="apply-btn" class="secondary">Apply Correction</button>' : ""}
      ${item.type === "room" ? '<button id="reclassify-btn" class="secondary">Reclassify</button>' : ""}
    </div>
    <div class="error-text" id="review-error"></div>
  `;

  document.getElementById("approve-btn").onclick = () => approveCurrent(item.object_id);

  if (item.type === "wall") {
    document.getElementById("apply-btn").onclick = () =>
      applyWallCorrection(item.object_id);
  } else if (item.type === "door" || item.type === "window") {
    document.getElementById("apply-btn").onclick = () =>
      applyOpeningCorrection(item.object_id);
  } else if (item.type === "room") {
    document.getElementById("reclassify-btn").onclick = () =>
      applyReclassify(item.object_id);
  }
}

function fieldsForType(type) {
  if (type === "wall") {
    return `
      <div class="field-row">
        <label>Field</label>
        <select id="field-select">
          <option value="thickness">Thickness</option>
          <option value="height">Height</option>
        </select>
      </div>
      <div class="field-row">
        <label>Value</label>
        <input id="value-input" placeholder="e.g. 6&quot; or 8' 0&quot;">
      </div>
    `;
  }
  if (type === "door" || type === "window") {
    return `
      <div class="field-row">
        <label>Field</label>
        <select id="field-select">
          <option value="width">Width</option>
          <option value="height">Height</option>
          <option value="sill_height">Sill height</option>
        </select>
      </div>
      <div class="field-row">
        <label>Value</label>
        <input id="value-input" placeholder="e.g. 3' 0&quot;">
      </div>
    `;
  }
  if (type === "room") {
    return `
      <div class="field-row">
        <label>Type</label>
        <input id="classification-input" placeholder="e.g. kitchen">
      </div>
    `;
  }
  return "";
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// --- API calls ---

async function fetchModel() {
  const resp = await fetch("/api/model");
  const data = await resp.json();
  if (!data.loaded) {
    currentModelData = null;
    setControlsEnabled(false);
    clearSvg();
    renderReviewItem(null);
    return;
  }
  currentModelData = data;
  setControlsEnabled(true);
  renderFloorplan(data);
  fetchNextReviewItem();
}

async function fetchNextReviewItem() {
  const resp = await fetch("/api/review/next");
  const data = await resp.json();
  renderReviewItem(data.item);
}

async function loadBundle() {
  const path = bundlePathEl.value.trim();
  if (!path) return;
  loadStatusEl.textContent = "Loading...";
  const resp = await fetch("/api/load_bundle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bundle_dir: path }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    loadStatusEl.textContent = "Error: " + data.error;
    return;
  }
  loadStatusEl.textContent = `Loaded (${data.capture_method})`;
  currentModelData = data;
  setControlsEnabled(true);
  renderFloorplan(data);
  fetchNextReviewItem();
}

async function approveCurrent(objectId) {
  await fetch("/api/review/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: objectId }),
  });
  await fetchModel();
}

async function applyWallCorrection(objectId) {
  const field = document.getElementById("field-select").value;
  const valueText = document.getElementById("value-input").value;
  const resp = await fetch("/api/review/correct_wall", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      object_id: objectId,
      field,
      value_text: valueText,
      unit_system: "us",
    }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    document.getElementById("review-error").textContent = data.error;
    return;
  }
  await fetchModel();
}

async function applyOpeningCorrection(objectId) {
  const field = document.getElementById("field-select").value;
  const valueText = document.getElementById("value-input").value;
  const resp = await fetch("/api/review/correct_opening", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      object_id: objectId,
      field,
      value_text: valueText,
      unit_system: "us",
    }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    document.getElementById("review-error").textContent = data.error;
    return;
  }
  await fetchModel();
}

async function applyReclassify(objectId) {
  const classification = document.getElementById("classification-input").value;
  const resp = await fetch("/api/review/reclassify_room", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: objectId, classification }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    document.getElementById("review-error").textContent = data.error;
    return;
  }
  await fetchModel();
}

async function reextractRooms() {
  const resp = await fetch("/api/reextract_rooms", { method: "POST" });
  const data = await resp.json();
  if (!resp.ok) return;
  currentModelData = data;
  renderFloorplan(data);
  fetchNextReviewItem();
}

async function exportIfc() {
  const resp = await fetch("/api/export_ifc", { method: "POST" });
  const data = await resp.json();
  if (!resp.ok) {
    alert("Export failed: " + (data.error || "unknown error"));
    return;
  }
  alert(`Exported to ${data.path}`);
}

// --- Draw-missing-wall interaction ---

function toggleDrawingMode() {
  drawingMode = !drawingMode;
  drawStartPoint = null;
  svgEl.classList.toggle("drawing-mode", drawingMode);
  drawHintEl.textContent = drawingMode
    ? "Click two points on the plan to draw a wall"
    : "";
  drawWallBtn.textContent = drawingMode ? "Cancel Drawing" : "Draw Missing Wall";
}

function handleSvgClick(evt) {
  if (!drawingMode) return;
  const rect = svgEl.getBoundingClientRect();
  const viewBox = svgEl.viewBox.baseVal;
  const svgX = ((evt.clientX - rect.left) / rect.width) * viewBox.width;
  const svgY = ((evt.clientY - rect.top) / rect.height) * viewBox.height;

  const transform = {
    scale: parseFloat(svgEl.dataset.scale),
    minX: parseFloat(svgEl.dataset.minX),
    minY: parseFloat(svgEl.dataset.minY),
    viewH: parseFloat(svgEl.dataset.viewH),
  };
  const [modelX, modelY] = toModelSpace(transform, svgX, svgY);

  if (!drawStartPoint) {
    drawStartPoint = [modelX, modelY];
    drawHintEl.textContent = "Click the wall's end point";
  } else {
    submitNewWall(drawStartPoint, [modelX, modelY]);
    drawStartPoint = null;
    toggleDrawingMode();
  }
}

async function submitNewWall(start, end) {
  const resp = await fetch("/api/review/add_wall", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start, end }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    alert("Could not add wall: " + data.error);
    return;
  }
  await fetchModel();
}

function setControlsEnabled(enabled) {
  drawWallBtn.disabled = !enabled;
  reextractBtn.disabled = !enabled;
  exportIfcBtn.disabled = !enabled;
}

// --- Wire up event listeners ---

loadBtn.addEventListener("click", loadBundle);
drawWallBtn.addEventListener("click", toggleDrawingMode);
reextractBtn.addEventListener("click", reextractRooms);
exportIfcBtn.addEventListener("click", exportIfc);
svgEl.addEventListener("click", handleSvgClick);

fetchModel();