const DEFAULT_SPATIAL = {
  environment: {
    site: { name: "Ambiente RF Sense" },
    bounds: { width: 8, depth: 6, height: 2.8 },
    rooms: [
      { id: "ambiente", name: "Ambiente", origin: [0, 0, 0], size: [8, 6, 2.8] },
    ],
    nodes: [
      {
        node_id: 1,
        name: "Nó 1",
        room_id: "ambiente",
        position: [0.6, 0.6, 1.2],
        coverage_radius_m: 4.5,
      },
    ],
    mesh_links: [],
  },
  nodes: [],
  people: [],
  rooms: [],
  summary: {
    people_count: 0,
    localized_count: 0,
    mesh_nodes_online: 0,
    mesh_ready: false,
    count_valid: false,
  },
};

export class EnvironmentMap3D {
  constructor(canvas, detail, summary) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.detail = detail;
    this.summary = summary;
    this.state = DEFAULT_SPATIAL;
    this.yaw = -0.62;
    this.pitch = 0.62;
    this.zoom = 1;
    this.dragging = false;
    this.last = null;
    this.hitTargets = [];
    this.selected = null;
    this.bind();
    this.resize();
    this.draw();
  }

  bind() {
    this.canvas.addEventListener("pointerdown", (event) => {
      this.canvas.setPointerCapture?.(event.pointerId);
      this.dragging = true;
      this.last = [event.clientX, event.clientY];
    });
    this.canvas.addEventListener("pointermove", (event) => {
      if (!this.dragging || !this.last) return;
      this.yaw += (event.clientX - this.last[0]) * 0.008;
      this.pitch = clamp(
        this.pitch + (event.clientY - this.last[1]) * 0.006,
        0.2,
        1.2,
      );
      this.last = [event.clientX, event.clientY];
      this.draw();
    });
    const release = (event) => {
      if (!this.dragging) return;
      const moved = this.last && Math.hypot(
        event.clientX - this.last[0],
        event.clientY - this.last[1],
      );
      this.dragging = false;
      if (!moved || moved < 4) this.selectAt(event);
      this.last = null;
    };
    this.canvas.addEventListener("pointerup", release);
    this.canvas.addEventListener("pointercancel", () => {
      this.dragging = false;
      this.last = null;
    });
    this.canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.zoom = clamp(this.zoom - event.deltaY * 0.001, 0.65, 1.8);
      this.draw();
    }, { passive: false });
    window.addEventListener("resize", () => this.resize());
  }

  update(spatial) {
    this.state = spatial?.environment ? spatial : DEFAULT_SPATIAL;
    const people = this.state.people ?? [];
    if (this.selected && !people.some((item) => item.track_id === this.selected)) {
      this.selected = null;
    }
    this.renderSummary();
    this.renderDetail();
    this.draw();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(rect.width * ratio));
    this.canvas.height = Math.max(1, Math.round(rect.height * ratio));
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.draw();
  }

  renderSummary() {
    const summary = this.state.summary ?? {};
    const count = summary.people_count ?? 0;
    const noun = count === 1 ? "pessoa" : "pessoas";
    const qualifier = summary.count_valid
      ? count === 1 ? "confirmada" : "confirmadas"
      : count === 1 ? "provável" : "prováveis";
    this.summary.innerHTML = `
      <span><b>${count}</b> ${noun} · ${qualifier}</span>
      <span><b>${summary.mesh_nodes_online ?? 0}</b> nós online</span>
      <span class="${summary.mesh_ready ? "valid" : ""}">
        ${summary.mesh_ready ? "MESH ATIVA" : "LOCALIZAÇÃO POR ZONA"}
      </span>
    `;
  }

  renderDetail() {
    const person = (this.state.people ?? []).find(
      (item) => item.track_id === this.selected,
    );
    if (!person) {
      this.detail.innerHTML = `
        <strong>Mapa espacial</strong>
        <p>Arraste para orbitar, role para ampliar e toque em uma pessoa.</p>
        <small>Posições sem três nós são exibidas apenas como zona provável.</small>
      `;
      return;
    }
    const room = (this.state.environment?.rooms ?? []).find(
      (item) => item.id === person.room_id,
    );
    const vitals = person.vital_signs ?? {};
    const position = person.position_valid
      ? `${person.position.map((item) => Number(item).toFixed(1)).join(", ")} m`
      : "apenas zona";
    this.detail.innerHTML = `
      <strong>${escapeHtml(room?.name ?? "Pessoa anônima")}</strong>
      <p>Posição: ${position} · incerteza ±${person.uncertainty_m ?? "—"} m</p>
      <dl>
        <div><dt>Respiração</dt><dd>${vitals.breathing_bpm ?? "—"} rpm</dd></div>
        <div><dt>Cardíaca</dt><dd>${vitals.heart_bpm ?? "—"} bpm</dd></div>
        <div><dt>Confiança</dt><dd>${Math.round((person.confidence ?? 0) * 100)}%</dd></div>
      </dl>
      <small>Estimativas experimentais; não usar para decisão médica.</small>
    `;
  }

  selectAt(event) {
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = this.hitTargets
      .filter((item) => Math.hypot(item.x - x, item.y - y) <= item.radius + 8)
      .sort((a, b) => a.depth - b.depth)[0];
    this.selected = hit?.id ?? null;
    this.renderDetail();
    this.draw();
  }

  project(point) {
    const bounds = this.state.environment.bounds;
    const rect = this.canvas.getBoundingClientRect();
    const center = [bounds.width / 2, bounds.depth / 2, bounds.height / 2];
    const x = point[0] - center[0];
    const y = point[1] - center[1];
    const z = point[2] - center[2];
    const cosYaw = Math.cos(this.yaw);
    const sinYaw = Math.sin(this.yaw);
    const rx = x * cosYaw - y * sinYaw;
    const ry = x * sinYaw + y * cosYaw;
    const cosPitch = Math.cos(this.pitch);
    const sinPitch = Math.sin(this.pitch);
    const py = ry * cosPitch - z * sinPitch;
    const depth = ry * sinPitch + z * cosPitch;
    const scale = Math.min(
      rect.width / (bounds.width + bounds.depth),
      rect.height / (bounds.depth + bounds.height),
    ) * 1.65 * this.zoom;
    return {
      x: rect.width / 2 + rx * scale,
      y: rect.height * 0.54 + py * scale,
      depth,
      scale,
    };
  }

  line(a, b, color, width = 1, dash = []) {
    const pa = this.project(a);
    const pb = this.project(b);
    const context = this.context;
    context.beginPath();
    context.moveTo(pa.x, pa.y);
    context.lineTo(pb.x, pb.y);
    context.strokeStyle = color;
    context.lineWidth = width;
    context.setLineDash(dash);
    context.stroke();
    context.setLineDash([]);
  }

  draw() {
    if (!this.context || !this.canvas.width) return;
    const context = this.context;
    const rect = this.canvas.getBoundingClientRect();
    context.clearRect(0, 0, rect.width, rect.height);
    const environment = this.state.environment ?? DEFAULT_SPATIAL.environment;
    this.drawGrid(environment.bounds);
    for (const room of environment.rooms ?? []) this.drawRoom(room);
    for (const link of environment.mesh_links ?? []) this.drawMeshLink(link);
    for (const node of environment.nodes ?? []) this.drawNode(node);
    this.hitTargets = [];
    for (const person of this.state.people ?? []) this.drawPerson(person);
  }

  drawGrid(bounds) {
    const step = 1;
    for (let x = 0; x <= bounds.width; x += step) {
      this.line([x, 0, 0], [x, bounds.depth, 0], "rgba(101,239,177,.07)");
    }
    for (let y = 0; y <= bounds.depth; y += step) {
      this.line([0, y, 0], [bounds.width, y, 0], "rgba(101,239,177,.07)");
    }
  }

  drawRoom(room) {
    const [x, y, z] = room.origin;
    const [w, d, h] = room.size;
    const floor = [[x, y, z], [x + w, y, z], [x + w, y + d, z], [x, y + d, z]];
    for (let index = 0; index < 4; index += 1) {
      this.line(floor[index], floor[(index + 1) % 4], "rgba(142,185,168,.42)", 1.3);
      this.line(floor[index], [floor[index][0], floor[index][1], z + h], "rgba(142,185,168,.14)");
    }
    const label = this.project([x + w / 2, y + d / 2, z]);
    this.context.fillStyle = "rgba(237,249,244,.42)";
    this.context.font = "600 11px -apple-system, sans-serif";
    this.context.textAlign = "center";
    this.context.fillText(room.name.toUpperCase(), label.x, label.y + 17);
  }

  drawMeshLink(link) {
    const nodes = this.state.environment.nodes ?? [];
    const aId = Array.isArray(link) ? link[0] : link.a;
    const bId = Array.isArray(link) ? link[1] : link.b;
    const a = nodes.find((item) => item.node_id === aId);
    const b = nodes.find((item) => item.node_id === bId);
    if (a && b) this.line(a.position, b.position, "rgba(101,239,177,.25)", 1, [4, 5]);
  }

  drawNode(node) {
    const point = this.project(node.position);
    const state = (this.state.nodes ?? []).find((item) => item.node_id === node.node_id);
    const online = state?.state === "online";
    const context = this.context;
    context.beginPath();
    context.arc(point.x, point.y, 5, 0, Math.PI * 2);
    context.fillStyle = online ? "#65efb1" : "#536a61";
    context.shadowColor = context.fillStyle;
    context.shadowBlur = online ? 12 : 0;
    context.fill();
    context.shadowBlur = 0;
    context.fillStyle = "#8aa79b";
    context.font = "10px -apple-system, sans-serif";
    context.textAlign = "left";
    context.fillText(`N${node.node_id}`, point.x + 8, point.y + 3);
  }

  drawPerson(person) {
    const point = this.project(person.position);
    const radius = person.position_valid ? 9 : 12;
    const selected = this.selected === person.track_id;
    const context = this.context;
    context.beginPath();
    context.arc(point.x, point.y, radius + (selected ? 4 : 0), 0, Math.PI * 2);
    context.fillStyle = person.position_valid
      ? "rgba(101,239,177,.88)"
      : "rgba(240,185,107,.76)";
    context.shadowColor = context.fillStyle;
    context.shadowBlur = selected ? 24 : 14;
    context.fill();
    context.shadowBlur = 0;
    context.beginPath();
    context.arc(point.x, point.y, Math.max(14, person.uncertainty_m * point.scale), 0, Math.PI * 2);
    context.strokeStyle = person.position_valid
      ? "rgba(101,239,177,.18)"
      : "rgba(240,185,107,.15)";
    context.stroke();
    this.hitTargets.push({
      id: person.track_id,
      x: point.x,
      y: point.y,
      depth: point.depth,
      radius,
    });
  }
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[character]);
}
