async function loadDashboard() {
  const statsNode = document.getElementById("stats");
  const gridNode = document.getElementById("capture-grid");

  try {
    const response = await fetch("/api/captures");
    const payload = await response.json();
    renderStats(statsNode, payload.stats);
    renderGrid(gridNode, payload.records);
  } catch (error) {
    gridNode.innerHTML = `
      <div class="empty-state">
        Dashboard failed to load capture data.
      </div>
    `;
  }
}

function renderStats(node, stats) {
  const cards = [
    ["Stored Captures", stats.capture_count],
    ["Average Speed", stats.average_speed ? `${stats.average_speed} km/h` : "No data"],
    ["Latest Capture", stats.latest_timestamp],
  ];

  node.innerHTML = cards.map(([label, value]) => `
    <article class="stat-card">
      <div class="stat-label">${escapeHtml(label)}</div>
      <div class="stat-value">${escapeHtml(String(value))}</div>
    </article>
  `).join("");
}

function renderGrid(node, records) {
  if (!records.length) {
    node.innerHTML = `
      <div class="empty-state">
        No captures yet. Once Odin's Eye records images and metadata, the latest 30 will appear here.
      </div>
    `;
    return;
  }

  node.innerHTML = records.map((record) => {
    const imageHtml = record.image_url
      ? `<img class="capture-image" src="${encodeURI(record.image_url)}" alt="Capture ${escapeHtml(record.timestamp_display)}">`
      : `<div class="image-empty">No image</div>`;

    return `
      <article class="capture-card">
        ${imageHtml}
        <div class="capture-body">
          <div class="capture-head">
            <div>
              <h3 class="capture-title">${escapeHtml(record.object_label || "Unknown object")}</h3>
              <p class="capture-time">${escapeHtml(String(record.timestamp_display))}</p>
            </div>
            <div class="speed-pill">${record.speed_kmh ? `${record.speed_kmh} km/h` : "Speed pending"}</div>
          </div>

          <div class="capture-meta">
            <div class="meta-block">
              <div class="meta-label">Plate</div>
              <div class="meta-value">${escapeHtml(String(record.license_plate || "Not available"))}</div>
            </div>
            <div class="meta-block">
              <div class="meta-label">Alignment</div>
              <div class="meta-value">${formatAligned(record.aligned)}</div>
            </div>
            <div class="meta-block">
              <div class="meta-label">Tilt</div>
              <div class="meta-value">${record.tilt_deg !== null && record.tilt_deg !== undefined ? `${record.tilt_deg} deg` : "Not logged"}</div>
            </div>
            <div class="meta-block">
              <div class="meta-label">Metadata</div>
              <div class="meta-value">${escapeHtml(String(record.metadata_file || "Image only"))}</div>
            </div>
          </div>

          <div class="capture-notes">${escapeHtml(String(record.notes || ""))}</div>
        </div>
      </article>
    `;
  }).join("");
}

function formatAligned(value) {
  if (value === true) return "Aligned";
  if (value === false) return "Out of range";
  return "Unknown";
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadDashboard();
setInterval(loadDashboard, 5000);
