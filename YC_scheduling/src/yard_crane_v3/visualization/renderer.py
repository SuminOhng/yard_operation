"""Dependency-free standalone HTML renderer for policy Gantt charts."""

from __future__ import annotations

import html
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .model import StaticScheduleVisualization
from .serialization import visualization_dict, write_visualization_data


@dataclass(frozen=True, slots=True)
class VisualizationBundlePaths:
    output_dir: Path
    index_html: Path
    data_json: Path


def render_schedule_visualization_html(
    visualization: StaticScheduleVisualization,
) -> str:
    payload = json.dumps(
        visualization_dict(visualization),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    title = html.escape(visualization.title, quote=True)
    return _HTML_TEMPLATE.replace("__TITLE__", title).replace(
        "__SCHEDULE_DATA__", payload
    )


def write_schedule_visualization_bundle(
    visualization: StaticScheduleVisualization,
    output_dir: str | Path,
) -> VisualizationBundlePaths:
    directory = Path(output_dir)
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(
            "visualization output directory must be absent or empty"
        )
    directory.mkdir(parents=True, exist_ok=True)
    data_path = write_visualization_data(
        visualization,
        directory / "visualization_data.json",
    )
    index_path = directory / "index.html"
    _write_text_atomic(
        index_path,
        render_schedule_visualization_html(visualization),
    )
    return VisualizationBundlePaths(directory, index_path, data_path)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            newline="",
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ - YC Schedule</title>
<style>
:root {
  color-scheme: light dark;
  --page: #f7f8fa;
  --surface: #ffffff;
  --text: #17202a;
  --muted: #68737d;
  --border: #d8dee4;
  --grid: #e7ebef;
  --empty: #82909d;
  --loaded: #2878c7;
  --pickup: #d78600;
  --drop: #14845d;
  --handover: #7452b8;
  --wait: #a8b0b8;
  --reshuffle: #c94a4a;
  --lb: #14845d;
  --ub: #c94a4a;
  --decision: #d78600;
  --sea: #1677c8;
  --land: #c84f42;
  --container-inbound: #158467;
  --container-outbound: #d98200;
  --container-unassigned: #77838f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #101418;
    --surface: #171c21;
    --text: #edf1f4;
    --muted: #a8b1ba;
    --border: #39424a;
    --grid: #2a3239;
    --empty: #93a1ad;
    --loaded: #63a8e8;
    --pickup: #f0ab3d;
    --drop: #48bd91;
    --handover: #a889e0;
    --wait: #65717c;
    --reshuffle: #e37676;
    --lb: #48bd91;
    --ub: #e37676;
    --decision: #f0ab3d;
    --sea: #5aa9e6;
    --land: #ef8177;
    --container-inbound: #57c6a3;
    --container-outbound: #f2b84b;
    --container-unassigned: #a8b1ba;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--text);
  font-family: Inter, "Noto Sans KR", system-ui, sans-serif;
}
main { max-width: 1200px; margin: 0 auto; padding: 24px; }
h1 { margin: 0 0 6px; font-size: clamp(1.35rem, 3vw, 2rem); }
h2 { margin: 0 0 12px; font-size: 1.05rem; }
.context { color: var(--muted); margin-bottom: 20px; }
.policy-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.policy-tabs button {
  appearance: none;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
  color: var(--text);
  padding: 8px 12px;
  cursor: pointer;
  font: inherit;
}
.policy-tabs button[aria-selected="true"] {
  border-color: var(--loaded);
  box-shadow: inset 0 0 0 1px var(--loaded);
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.stat-label { color: var(--muted); font-size: .82rem; }
.stat-value { margin-top: 4px; font-size: 1.2rem; font-weight: 600; }
.candidate-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 14px;
  margin-bottom: 16px;
}
.candidate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
}
.candidate-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 11px;
}
.candidate-card.selected { border-color: var(--drop); }
.candidate-title { font-weight: 700; }
.candidate-value { font-size: 1.35rem; margin: 5px 0; }
.candidate-meta { color: var(--muted); font-size: .8rem; overflow-wrap: anywhere; }
.chart-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 14px;
}
.chart-panel + .chart-panel { margin-top: 16px; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; color: var(--muted); font-size: .82rem; }
.legend-item { display: inline-flex; align-items: center; gap: 5px; }
.swatch { width: 12px; height: 12px; border-radius: 2px; }
.replay-icon { display: inline-block; width: 12px; height: 12px; border: 1px solid currentColor; }
.replay-icon-inbound { border-radius: 50%; background: var(--container-inbound); color: var(--container-inbound); }
.replay-icon-outbound { background: var(--container-outbound); color: var(--container-outbound); transform: rotate(45deg) scale(.78); }
.replay-icon-unassigned { background: var(--container-unassigned); color: var(--container-unassigned); }
.replay-icon-sea { width: 22px; border-radius: 3px; background: var(--sea); color: var(--sea); }
.replay-icon-land { width: 22px; border-radius: 3px; background: var(--land); color: var(--land); }
.replay-icon-transfer { background: color-mix(in srgb, var(--handover) 30%, transparent); color: var(--handover); }
.replay-icon-virtual-transfer { background: transparent; color: var(--handover); border-style: dashed; transform: rotate(45deg) scale(.78); }
.replay-icon-h-line { width: 22px; height: 0; border: 0; border-top: 2px dashed var(--handover); }
#gantt { display: block; width: 100%; min-height: 230px; }
.axis-text, .lane-text, .marker-text, .bar-text { fill: var(--text); font-family: inherit; }
.axis-text, .marker-text { font-size: 11px; }
.lane-text { font-size: 12px; font-weight: 600; }
.bar-text { fill: #fff; font-size: 10px; pointer-events: none; }
.grid-line { stroke: var(--grid); stroke-width: 1; }
.axis-line { stroke: var(--border); stroke-width: 1; }
.marker-lb { stroke: var(--lb); stroke-width: 2; stroke-dasharray: 5 4; }
.marker-ub { stroke: var(--ub); stroke-width: 2; }
.marker-decision { stroke: var(--decision); stroke-width: 1.5; stroke-dasharray: 2 4; }
.operation { cursor: pointer; stroke: color-mix(in srgb, currentColor 70%, transparent); stroke-width: .5; }
.operation:focus { outline: none; stroke: var(--text); stroke-width: 2; }
.op-empty { fill: var(--empty); color: var(--empty); }
.op-loaded { fill: var(--loaded); color: var(--loaded); }
.op-pickup { fill: var(--pickup); color: var(--pickup); }
.op-drop { fill: var(--drop); color: var(--drop); }
.op-handover { fill: var(--handover); color: var(--handover); }
.op-wait { fill: var(--wait); color: var(--wait); }
.op-reshuffle { fill: var(--reshuffle); color: var(--reshuffle); }
.detail {
  min-height: 48px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  color: var(--muted);
}
.detail strong { color: var(--text); }
.validation { margin: 12px 0 0; color: var(--muted); }
.validation.error { color: var(--reshuffle); }
.replay-controls {
  display: grid;
  grid-template-columns: auto auto minmax(180px, 1fr) auto auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}
.replay-controls button, .replay-controls select {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  padding: 7px 10px;
  font: inherit;
}
.replay-controls input { width: 100%; }
#yard-replay { display: block; width: 100%; min-height: 310px; }
.yard-cell { fill: none; stroke: var(--grid); stroke-width: 1; }
.handover-line { stroke: var(--handover); stroke-width: 2; stroke-dasharray: 5 4; }
.transfer-marker { fill: color-mix(in srgb, var(--handover) 30%, transparent); stroke: var(--handover); }
.virtual-transfer-marker { fill: color-mix(in srgb, var(--handover) 12%, transparent); stroke: var(--handover); stroke-width: 1.5; stroke-dasharray: 3 2; }
.crane-sea { fill: var(--sea); }
.crane-land { fill: var(--land); }
.crane-label, .yard-label, .container-label { fill: var(--text); font-family: inherit; }
.crane-label { fill: #fff; font-size: 10px; font-weight: 700; }
.yard-label { font-size: 10px; }
.container-dot { stroke-width: 1.2; }
.container-inbound { fill: var(--container-inbound); stroke: color-mix(in srgb, var(--container-inbound) 60%, #000); }
.container-outbound { fill: var(--container-outbound); stroke: color-mix(in srgb, var(--container-outbound) 60%, #000); }
.container-unassigned { fill: var(--container-unassigned); stroke: color-mix(in srgb, var(--container-unassigned) 60%, #000); }
.container-label { font-size: 8px; pointer-events: none; }
.replay-status { color: var(--muted); font-size: .85rem; margin-top: 8px; }
@media (max-width: 600px) {
  main { padding: 14px; }
  .chart-panel { padding: 8px; }
  .replay-controls { grid-template-columns: auto auto 1fr; }
  .replay-controls label { grid-column: 1 / -1; }
}
</style>
</head>
<body>
<main>
  <h1 id="page-title"></h1>
  <div class="context" id="context"></div>
  <section class="candidate-panel" aria-label="운반 후보 makespan 비교">
    <h2>운반 후보 makespan (미채택 포함)</h2>
    <div class="candidate-grid" id="route-candidates"></div>
  </section>
  <div class="policy-tabs" id="policy-tabs" role="tablist" aria-label="야드크레인 정책"></div>
  <section class="stats" id="stats" aria-label="정적 일정 결과"></section>
  <section class="chart-panel" aria-label="크레인 작업 Gantt Chart">
    <div class="legend" aria-label="작업 유형 범례">
      <span class="legend-item"><span class="swatch op-empty"></span>빈 이동</span>
      <span class="legend-item"><span class="swatch op-loaded"></span>적재 이동</span>
      <span class="legend-item"><span class="swatch op-pickup"></span>Pickup</span>
      <span class="legend-item"><span class="swatch op-drop"></span>Final drop</span>
      <span class="legend-item"><span class="swatch op-handover"></span>Handover</span>
      <span class="legend-item"><span class="swatch op-reshuffle"></span>Reshuffle</span>
    </div>
    <svg id="gantt" role="img" aria-labelledby="gantt-title gantt-desc">
      <title id="gantt-title">두 야드크레인의 작업 일정</title>
      <desc id="gantt-desc">정책별 동일 시간축 Gantt Chart</desc>
    </svg>
    <div class="detail" id="operation-detail">작업 막대를 선택하면 상세정보가 표시됩니다.</div>
  </section>
  <section class="chart-panel" aria-label="야드크레인 공간 리플레이">
    <h2>크레인·컨테이너 이동 리플레이</h2>
    <div class="legend" aria-label="공간 리플레이 아이콘 범례">
      <span class="legend-item"><span class="replay-icon replay-icon-inbound"></span>수입 컨테이너 (INBOUND)</span>
      <span class="legend-item"><span class="replay-icon replay-icon-outbound"></span>수출 컨테이너 (OUTBOUND)</span>
      <span class="legend-item"><span class="replay-icon replay-icon-unassigned"></span>작업 미지정 컨테이너</span>
      <span class="legend-item"><span class="replay-icon replay-icon-sea"></span>해측 YC</span>
      <span class="legend-item"><span class="replay-icon replay-icon-land"></span>육측 YC</span>
      <span class="legend-item"><span class="replay-icon replay-icon-transfer"></span>고정 Transfer buffer</span>
      <span class="legend-item"><span class="replay-icon replay-icon-virtual-transfer"></span>ANY 임시 Stack 인계점</span>
      <span class="legend-item"><span class="replay-icon replay-icon-h-line"></span>H bay</span>
    </div>
    <div class="replay-controls">
      <button type="button" id="replay-play">재생</button>
      <button type="button" id="replay-reset">처음</button>
      <input id="replay-time" type="range" min="0" max="1" step="0.05" value="0" aria-label="리플레이 시간">
      <output id="replay-clock">0.0초</output>
      <label>속도 <select id="replay-speed"><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="8" selected>8×</option><option value="16">16×</option><option value="32">32×</option></select></label>
    </div>
    <svg id="yard-replay" role="img" aria-label="시간별 야드크레인과 컨테이너 위치"></svg>
    <div class="replay-status" id="replay-status"></div>
  </section>
  <p class="validation" id="validation-note"></p>
</main>
<script type="application/json" id="schedule-data">__SCHEDULE_DATA__</script>
<script>
(() => {
  "use strict";
  const payload = JSON.parse(document.getElementById("schedule-data").textContent);
  const instance = payload.instance;
  const policies = payload.policies;
  const tabs = document.getElementById("policy-tabs");
  const stats = document.getElementById("stats");
  const candidateGrid = document.getElementById("route-candidates");
  const svg = document.getElementById("gantt");
  const replaySvg = document.getElementById("yard-replay");
  const replayTime = document.getElementById("replay-time");
  const replayClock = document.getElementById("replay-clock");
  const replayPlay = document.getElementById("replay-play");
  const replayReset = document.getElementById("replay-reset");
  const replaySpeed = document.getElementById("replay-speed");
  const replayStatus = document.getElementById("replay-status");
  const detail = document.getElementById("operation-detail");
  const validationNote = document.getElementById("validation-note");
  let selectedPolicy = 0;
  let replayRunning = false;
  let replayAnimation = null;
  let previousFrame = null;

  document.getElementById("page-title").textContent = instance.title;
  document.getElementById("context").textContent =
    `${instance.block_id} · 작업 bay 1-${instance.work_bays} · 전체 작업 ${instance.existing_job_ids.length + instance.new_job_ids.length}건`;

  const routeNames = {
    DIRECT: "직접 운반",
    H_HANDOVER: "H handover",
    ANY_BAY_HANDOVER: "ANY_BAY handover",
  };
  const policiesByName = new Map(policies.map(policy => [policy.policy, policy]));

  payload.route_candidates.forEach(candidate => {
    const policy = policiesByName.get(candidate.policy);
    const card = document.createElement("article");
    card.className = `candidate-card${candidate.selected ? " selected" : ""}`;
    const title = document.createElement("div");
    title.className = "candidate-title";
    title.textContent = routeNames[candidate.route_key] || candidate.route_key;
    const value = document.createElement("div");
    value.className = "candidate-value";
    value.textContent = candidate.valid
      ? `${candidate.selected ? "채택" : "후보"} ${formatTime(candidate.makespan)}`
      : "실행 불가";
    const meta = document.createElement("div");
    meta.className = "candidate-meta";
    if (candidate.valid) {
      const status = candidate.selected ? "정책 채택" : "미채택 후보";
      const policyValue = policy && !candidate.selected
        ? ` · 실제 ${candidate.policy} ${formatTime(policy.schedule_makespan)}`
        : "";
      meta.textContent = `${status} · handover ${candidate.handover_count}회 · operation ${candidate.operation_count}개${policyValue}`;
    } else {
      meta.textContent = candidate.error || "후보 없음";
    }
    card.append(title, value, meta);
    candidateGrid.appendChild(card);
  });

  policies.forEach((policy, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.role = "tab";
    button.textContent = policy.policy;
    button.setAttribute("aria-selected", String(index === selectedPolicy));
    button.addEventListener("click", () => {
      selectedPolicy = index;
      update();
    });
    tabs.appendChild(button);
  });

  function formatNumber(value, digits = 1) {
    return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
  }

  function formatTime(value) {
    return value === null || value === undefined ? "-" : `${formatNumber(value)}초`;
  }

  function formatGap(value) {
    return value === null || value === undefined ? "-" : `${(100 * value).toFixed(1)}%`;
  }

  function addStat(label, value) {
    const node = document.createElement("div");
    node.className = "stat";
    const labelNode = document.createElement("div");
    labelNode.className = "stat-label";
    labelNode.textContent = label;
    const valueNode = document.createElement("div");
    valueNode.className = "stat-value";
    valueNode.textContent = value;
    node.append(labelNode, valueNode);
    stats.appendChild(node);
  }

  function svgNode(name, attributes = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function operationClass(operation) {
    if (operation.purpose === "RESHUFFLE") return "op-reshuffle";
    if (operation.operation_type === "MOVE_EMPTY") return "op-empty";
    if (operation.operation_type === "MOVE_LOADED") return "op-loaded";
    if (operation.operation_type === "PICKUP") return "op-pickup";
    if (operation.operation_type === "FINAL_DROP") return "op-drop";
    if (operation.operation_type.startsWith("HANDOVER")) return "op-handover";
    return "op-wait";
  }

  function operationSummary(operation) {
    const identity = operation.job_id || operation.container_id || "공통 이동";
    return `${identity} · ${operation.operation_type} · ${formatNumber(operation.start_time)}-${formatNumber(operation.end_time)}초 · Bay ${operation.start_position.bay}, Row ${operation.start_position.row} to Bay ${operation.end_position.bay}, Row ${operation.end_position.row}`;
  }

  function showOperation(operation) {
    detail.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = `#${operation.operation_index} ${operation.crane_id}`;
    detail.append(strong, document.createTextNode(` · ${operationSummary(operation)}`));
    if (operation.transfer_slot_id) {
      detail.append(document.createTextNode(` · Transfer ${operation.transfer_slot_id}`));
    }
  }

  function addMarker(group, x, top, bottom, className, label, labelY) {
    group.appendChild(svgNode("line", {x1: x, x2: x, y1: top, y2: bottom, class: className}));
    const text = svgNode("text", {x: x + 4, y: labelY, class: "marker-text"});
    text.textContent = label;
    group.appendChild(text);
  }

  function renderGantt(policy) {
    svg.replaceChildren();
    const width = Math.max(720, Math.round(svg.getBoundingClientRect().width || 900));
    const cranes = policy.crane_ids.length ? policy.crane_ids : ["C_SEA", "C_LAND"];
    const margin = {left: 104, right: 28, top: 58, bottom: 42};
    const laneHeight = 64;
    const height = margin.top + laneHeight * cranes.length + margin.bottom;
    const plotWidth = width - margin.left - margin.right;
    const horizon = Math.max(1, instance.shared_time_horizon);
    const x = time => margin.left + (Number(time) / horizon) * plotWidth;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("height", String(height));

    const root = svgNode("g");
    svg.appendChild(root);
    const ticks = 6;
    for (let index = 0; index <= ticks; index += 1) {
      const value = horizon * index / ticks;
      const tickX = x(value);
      root.appendChild(svgNode("line", {
        x1: tickX, x2: tickX, y1: margin.top, y2: height - margin.bottom, class: "grid-line"
      }));
      const label = svgNode("text", {
        x: tickX, y: height - 14, "text-anchor": "middle", class: "axis-text"
      });
      label.textContent = formatNumber(value);
      root.appendChild(label);
    }
    const axisTitle = svgNode("text", {
      x: margin.left + plotWidth / 2, y: height - 1, "text-anchor": "middle", class: "axis-text"
    });
    axisTitle.textContent = "시간 (초)";
    root.appendChild(axisTitle);

    cranes.forEach((crane, laneIndex) => {
      const laneTop = margin.top + laneIndex * laneHeight;
      root.appendChild(svgNode("line", {
        x1: margin.left, x2: width - margin.right, y1: laneTop + laneHeight, y2: laneTop + laneHeight, class: "axis-line"
      }));
      const laneLabel = svgNode("text", {
        x: margin.left - 12, y: laneTop + 34, "text-anchor": "end", class: "lane-text"
      });
      laneLabel.textContent = crane;
      root.appendChild(laneLabel);
    });

    if (policy.upper_bound_validated && policy.best_known_upper_bound !== null) {
      addMarker(root, x(policy.best_known_upper_bound), margin.top, height - margin.bottom, "marker-ub", `Makespan ${formatNumber(policy.best_known_upper_bound)}초`, 42);
    }

    policy.operations.forEach(operation => {
      const laneIndex = Math.max(0, cranes.indexOf(operation.crane_id));
      const startX = x(operation.start_time);
      const endX = x(operation.end_time);
      const barWidth = Math.max(2, endX - startX);
      const y = margin.top + laneIndex * laneHeight + 14;
      const rect = svgNode("rect", {
        x: startX,
        y,
        width: barWidth,
        height: 32,
        rx: 3,
        class: `operation ${operationClass(operation)}`,
        tabindex: 0,
        role: "button",
        "aria-label": operationSummary(operation),
      });
      const nativeTitle = svgNode("title");
      nativeTitle.textContent = operationSummary(operation);
      rect.appendChild(nativeTitle);
      rect.addEventListener("click", () => showOperation(operation));
      rect.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          showOperation(operation);
        }
      });
      root.appendChild(rect);
      if (barWidth >= 64) {
        const label = svgNode("text", {
          x: startX + 5, y: y + 20, class: "bar-text"
        });
        label.textContent = operation.operation_type.replace("MOVE_", "");
        root.appendChild(label);
      }
    });
  }

  function copyInitialState() {
    const cranes = new Map(instance.initial_cranes.map(crane => [crane.crane_id, {
      crane_id: crane.crane_id,
      side: crane.side,
      bay: Number(crane.position.bay),
      row: Number(crane.position.row),
      load: crane.carrying_container,
    }]));
    const containers = new Map(instance.initial_containers.map(container => [container.container_id, {
      container_id: container.container_id,
      direction: container.direction,
      status: container.status,
      position: container.position ? {...container.position} : null,
      tier: container.tier,
      carried_by: container.carried_by,
      transfer_slot_id: container.transfer_slot_id,
    }]));
    return {cranes, containers};
  }

  function replayStateAt(policy, time) {
    const state = copyInitialState();
    const completed = policy.operations
      .filter(operation => operation.accepted && operation.end_time <= time + 1e-9)
      .sort((left, right) => left.end_time - right.end_time || left.operation_index - right.operation_index);
    completed.forEach(operation => {
      const crane = state.cranes.get(operation.crane_id);
      if (crane) {
        crane.bay = Number(operation.end_position.bay);
        crane.row = Number(operation.end_position.row);
        crane.load = operation.state_after.crane_load;
      }
      if (!operation.container_id || !operation.state_after.container_status) return;
      const container = state.containers.get(operation.container_id) || {
        container_id: operation.container_id,
        direction: null,
        position: null,
        tier: null,
      };
      container.status = operation.state_after.container_status;
      container.carried_by = container.status === "ON_CRANE" ? operation.crane_id : null;
      container.transfer_slot_id = operation.state_after.transfer_slot_id;
      if (operation.state_after.container_slot) {
        container.position = {
          bay: operation.state_after.container_slot.bay,
          row: operation.state_after.container_slot.row,
        };
        container.tier = operation.state_after.container_slot.tier;
      } else if (container.status === "AT_TRANSFER_SLOT") {
        const transfer = instance.transfer_slots.find(item => item.slot_id === container.transfer_slot_id);
        container.position = transfer ? {...transfer.position} : {...operation.end_position};
        container.tier = null;
      } else if (container.status === "COMPLETED") {
        container.position = {...operation.end_position};
        container.tier = null;
      } else if (container.status === "ON_CRANE") {
        container.position = null;
        container.tier = null;
      }
      state.containers.set(container.container_id, container);
    });
    const active = policy.operations.filter(operation =>
      operation.accepted && operation.start_time <= time + 1e-9 && time < operation.end_time - 1e-9
    );
    active.forEach(operation => {
      const crane = state.cranes.get(operation.crane_id);
      if (!crane) return;
      const duration = operation.end_time - operation.start_time;
      const ratio = duration <= 0 ? 1 : Math.max(0, Math.min(1, (time - operation.start_time) / duration));
      crane.bay = Number(operation.start_position.bay) + ratio * (Number(operation.end_position.bay) - Number(operation.start_position.bay));
      crane.row = Number(operation.start_position.row) + ratio * (Number(operation.end_position.row) - Number(operation.start_position.row));
    });
    return {state, active};
  }

  function containerDirectionLabel(direction) {
    if (direction === "INBOUND") return "수입(INBOUND)";
    if (direction === "OUTBOUND") return "수출(OUTBOUND)";
    return "작업 미지정";
  }

  function containerMarker(container, cx, cy) {
    const common = {class: "container-dot"};
    let marker;
    if (container.direction === "INBOUND") {
      marker = svgNode("circle", {cx, cy, r: 5, ...common, class: `${common.class} container-inbound`});
    } else if (container.direction === "OUTBOUND") {
      marker = svgNode("rect", {
        x: cx - 4.5, y: cy - 4.5, width: 9, height: 9,
        transform: `rotate(45 ${cx} ${cy})`,
        ...common, class: `${common.class} container-outbound`,
      });
    } else {
      marker = svgNode("rect", {
        x: cx - 4.5, y: cy - 4.5, width: 9, height: 9, rx: 1,
        ...common, class: `${common.class} container-unassigned`,
      });
    }
    const title = svgNode("title");
    title.textContent = `${container.container_id} · ${containerDirectionLabel(container.direction)} · ${container.status || "ON_CRANE"}${container.tier ? ` · tier ${container.tier}` : ""}`;
    marker.appendChild(title);
    return marker;
  }

  function usedTransferPoints(policy) {
    const fixed = new Map(instance.transfer_slots.map(slot => [slot.slot_id, slot]));
    const points = new Map();
    policy.operations.forEach(operation => {
      if (!operation.transfer_slot_id) return;
      let point = points.get(operation.transfer_slot_id);
      if (!point) {
        const configured = fixed.get(operation.transfer_slot_id);
        point = {
          slot_id: operation.transfer_slot_id,
          position: configured ? {...configured.position} : {...operation.start_position},
          capacity: configured ? configured.capacity : 1,
          kind: operation.transfer_point_kind || "FIXED_BUFFER",
          intervals: [],
          pending: new Map(),
        };
        points.set(operation.transfer_slot_id, point);
      }
      const containerKey = operation.container_id || operation.job_id;
      if (operation.operation_type === "HANDOVER_DROP" && containerKey) {
        point.pending.set(containerKey, {
          start: operation.end_time,
          tier: operation.state_after.container_slot?.tier ?? null,
        });
      } else if (operation.operation_type === "HANDOVER_PICKUP" && containerKey) {
        const drop = point.pending.get(containerKey);
        if (drop) {
          point.intervals.push({
            container_id: operation.container_id,
            start: drop.start,
            end: operation.end_time,
            tier: drop.tier,
          });
          point.pending.delete(containerKey);
        }
      }
    });
    return [...points.values()];
  }

  function renderReplay(policy, time) {
    replaySvg.replaceChildren();
    const width = Math.max(720, Math.round(replaySvg.getBoundingClientRect().width || 900));
    const height = 330;
    const margin = {left: 38, right: 38, top: 42, bottom: 42};
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maxBay = instance.landside_parking_bay;
    const x = bay => margin.left + Number(bay) / maxBay * plotWidth;
    const y = row => instance.rows === 1
      ? margin.top + plotHeight / 2
      : margin.top + (Number(row) - 1) / (instance.rows - 1) * plotHeight;
    replaySvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    replaySvg.setAttribute("height", String(height));
    const root = svgNode("g");
    replaySvg.appendChild(root);

    for (let bay = instance.seaside_parking_bay; bay <= instance.landside_parking_bay; bay += 1) {
      root.appendChild(svgNode("line", {
        x1: x(bay), x2: x(bay), y1: margin.top - 12, y2: height - margin.bottom + 12, class: "grid-line"
      }));
      const label = svgNode("text", {x: x(bay), y: height - 13, "text-anchor": "middle", class: "yard-label"});
      label.textContent = bay === 0 ? "SEA 0" : bay === maxBay ? `LAND ${bay}` : String(bay);
      root.appendChild(label);
    }
    for (let row = 1; row <= instance.rows; row += 1) {
      root.appendChild(svgNode("line", {
        x1: x(0), x2: x(maxBay), y1: y(row), y2: y(row), class: "grid-line"
      }));
      const label = svgNode("text", {x: 5, y: y(row) + 3, class: "yard-label"});
      label.textContent = `R${row}`;
      root.appendChild(label);
    }
    root.appendChild(svgNode("line", {
      x1: x(instance.handshake_bay), x2: x(instance.handshake_bay),
      y1: margin.top - 20, y2: height - margin.bottom + 15, class: "handover-line"
    }));
    usedTransferPoints(policy).forEach(point => {
      const virtual = point.kind === "VIRTUAL_STACK";
      const stackBacked = virtual || point.kind === "STACK_BACKED";
      const marker = svgNode("rect", {
        x: x(point.position.bay) - 7, y: y(point.position.row) - 7,
        width: 14, height: 14, rx: virtual ? 0 : 2,
        transform: virtual ? `rotate(45 ${x(point.position.bay)} ${y(point.position.row)})` : "",
        class: virtual ? "virtual-transfer-marker" : "transfer-marker"
      });
      const title = svgNode("title");
      const usage = point.intervals.map(interval => {
        const tier = interval.tier == null ? "" : ` · 임시 tier ${interval.tier}`;
        return `${interval.container_id || "container"}${tier} · 점유 ${formatNumber(interval.start)}-${formatNumber(interval.end)}초`;
      }).join(" / ");
      title.textContent = virtual
        ? `${point.slot_id} · Bay ${point.position.bay}, Row ${point.position.row} · ANY 임시 stack 인계점 · capacity ${point.capacity}${usage ? ` · ${usage}` : ""}`
        : stackBacked
          ? `${point.slot_id} · Bay ${point.position.bay}, Row ${point.position.row} · 실제 stack 상단 H 인계점 · capacity ${point.capacity}${usage ? ` · ${usage}` : ""}`
          : `${point.slot_id} · Bay ${point.position.bay}, Row ${point.position.row} · 고정 transfer buffer · capacity ${point.capacity}${usage ? ` · ${usage}` : ""}`;
      marker.appendChild(title);
      root.appendChild(marker);
    });

    const replay = replayStateAt(policy, time);
    const visibleContainers = [...replay.state.containers.values()].filter(container =>
      container.status !== "ON_CRANE" && container.status !== "COMPLETED" && container.position
    );
    const locationCounts = new Map();
    visibleContainers.forEach(container => {
      const key = `${container.position.bay}:${container.position.row}`;
      const offset = locationCounts.get(key) || 0;
      locationCounts.set(key, offset + 1);
      const cx = x(container.position.bay) + (offset % 3 - 1) * 7;
      const cy = y(container.position.row) - Math.floor(offset / 3) * 9;
      root.appendChild(containerMarker(container, cx, cy));
    });

    const cranes = [...replay.state.cranes.values()].sort((left, right) => left.bay - right.bay);
    cranes.forEach(crane => {
      const craneX = x(crane.bay);
      const craneY = y(crane.row);
      const group = svgNode("g");
      const rect = svgNode("rect", {
        x: craneX - 25, y: craneY - 14, width: 50, height: 28, rx: 5,
        class: crane.side === "SEASIDE" ? "crane-sea" : "crane-land"
      });
      const title = svgNode("title");
      title.textContent = `${crane.crane_id} · Bay ${formatNumber(crane.bay, 2)}, Row ${formatNumber(crane.row, 2)}${crane.load ? ` · ${crane.load} 적재` : " · empty"}`;
      rect.appendChild(title);
      const text = svgNode("text", {x: craneX, y: craneY + 3, "text-anchor": "middle", class: "crane-label"});
      text.textContent = crane.crane_id;
      group.append(rect, text);
      if (crane.load) {
        const carried = replay.state.containers.get(crane.load) || {
          container_id: crane.load,
          direction: null,
          status: "ON_CRANE",
          tier: null,
        };
        group.appendChild(containerMarker(carried, craneX + 19, craneY - 10));
      }
      root.appendChild(group);
    });

    const separation = cranes.length === 2 ? cranes[1].bay - cranes[0].bay : null;
    const activeText = replay.active.length
      ? replay.active.map(operation => `${operation.crane_id}: ${operation.operation_type} ${operation.job_id || operation.container_id || ""}`.trim()).join(" | ")
      : "두 크레인 대기";
    replayStatus.textContent = `t=${formatTime(time)} · ${activeText}${separation === null ? "" : ` · crane gap ${formatNumber(separation, 2)} bay (최소 ${formatNumber(instance.minimum_crane_separation_bays, 2)})`}`;
  }

  function stopReplay() {
    replayRunning = false;
    replayPlay.textContent = "재생";
    previousFrame = null;
    if (replayAnimation !== null) cancelAnimationFrame(replayAnimation);
    replayAnimation = null;
  }

  function setReplayTime(value) {
    const maximum = Number(replayTime.max);
    const normalized = Math.max(0, Math.min(maximum, Number(value)));
    replayTime.value = String(normalized);
    replayClock.textContent = formatTime(normalized);
    renderReplay(policies[selectedPolicy], normalized);
  }

  function replayFrame(timestamp) {
    if (!replayRunning) return;
    if (previousFrame === null) previousFrame = timestamp;
    const elapsed = (timestamp - previousFrame) / 1000 * Number(replaySpeed.value);
    previousFrame = timestamp;
    const next = Number(replayTime.value) + elapsed;
    if (next >= Number(replayTime.max)) {
      setReplayTime(Number(replayTime.max));
      stopReplay();
      return;
    }
    setReplayTime(next);
    replayAnimation = requestAnimationFrame(replayFrame);
  }

  function configureReplay(policy) {
    stopReplay();
    replayTime.min = "0";
    replayTime.max = String(Math.max(1, policy.schedule_makespan || 1));
    replayTime.step = "0.05";
    setReplayTime(0);
  }

  replayPlay.addEventListener("click", () => {
    if (replayRunning) {
      stopReplay();
      return;
    }
    if (Number(replayTime.value) >= Number(replayTime.max) - 1e-9) setReplayTime(0);
    replayRunning = true;
    replayPlay.textContent = "일시정지";
    previousFrame = null;
    replayAnimation = requestAnimationFrame(replayFrame);
  });
  replayReset.addEventListener("click", () => {
    stopReplay();
    setReplayTime(0);
  });
  replayTime.addEventListener("input", () => {
    stopReplay();
    setReplayTime(replayTime.value);
  });

  function update() {
    [...tabs.children].forEach((button, index) => {
      button.setAttribute("aria-selected", String(index === selectedPolicy));
    });
    const policy = policies[selectedPolicy];
    stats.replaceChildren();
    addStat("Makespan", formatTime(policy.schedule_makespan ?? policy.best_known_upper_bound));
    addStat("Handover", `${policy.handover_count}회`);
    addStat("Reshuffle", `${policy.reshuffle_count}회`);
    addStat("두 크레인 동시작업", formatTime(policy.concurrent_crane_seconds));
    addStat("평균 transfer 대기", formatTime(policy.average_transfer_wait_seconds));
    detail.textContent = "작업 막대를 선택하면 상세정보가 표시됩니다.";
    validationNote.className = policy.schedule_valid ? "validation" : "validation error";
    validationNote.textContent = policy.schedule_valid
      ? `공통 물리 Validator 통과 · ${policy.operations.length}개 operation · ${policy.status}`
      : `실행 가능한 일정 없음 · ${policy.error || policy.violation_codes.join(", ") || policy.status}`;
    renderGantt(policy);
    configureReplay(policy);
  }

  let resizeTimer = null;
  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      renderGantt(policies[selectedPolicy]);
      renderReplay(policies[selectedPolicy], Number(replayTime.value));
    }, 80);
  });
  observer.observe(svg.parentElement);
  update();
})();
</script>
</body>
</html>
"""
