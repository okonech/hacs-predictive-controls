/** Light-DOM styles: every selector is scoped to the custom-element host.
 * Path components use path-role-presence/history/candidate/neutral on cards,
 * path chips, and SVG paths; warning styles change color, never role line shape.
 */
export const panelStyles = `
  predictive-controls-panel { display:block; width:100%; min-width:0; --pc-presence:#00897b; --pc-history:#8053b3; --pc-candidate:#608e89; }
  predictive-controls-panel .pc-shell { padding:24px; color:var(--primary-text-color); min-width:0; box-sizing:border-box; }
  predictive-controls-panel header { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; }
  predictive-controls-panel h1 { margin:0; font-size:28px; }
  predictive-controls-panel h2 { margin:0 0 12px; font-size:18px; }
  predictive-controls-panel h3 { margin:18px 0 8px; font-size:14px; }
  predictive-controls-panel p { color:var(--secondary-text-color); }
  predictive-controls-panel button { border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); border-radius:6px; padding:8px 12px; cursor:pointer; font:inherit; min-height:44px; touch-action:manipulation; }
  predictive-controls-panel button.primary, predictive-controls-panel button.active { background:var(--primary-color); color:var(--text-primary-color); border-color:var(--primary-color); }
  predictive-controls-panel button:disabled { opacity:.5; cursor:not-allowed; }
  predictive-controls-panel nav { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
  predictive-controls-panel .pc-actions { display:flex; gap:8px; flex-wrap:wrap; }
  predictive-controls-panel .map-layout { display:grid; grid-template-columns:280px minmax(420px, 1fr) 280px; gap:16px; min-height:640px; }
  predictive-controls-panel .entity-list, predictive-controls-panel .board-wrap, predictive-controls-panel .inspector, predictive-controls-panel .single-panel { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .entity-list input, predictive-controls-panel label input, predictive-controls-panel textarea, predictive-controls-panel select { width:100%; box-sizing:border-box; margin-top:6px; padding:8px; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:6px; font:inherit; min-height:44px; }
  predictive-controls-panel .entities { margin-top:12px; display:grid; gap:8px; max-height:560px; overflow:auto; }
  predictive-controls-panel .entity { border:1px solid var(--divider-color); border-radius:6px; padding:10px; cursor:grab; }
  predictive-controls-panel .entity span, predictive-controls-panel .entity small, predictive-controls-panel .node span, predictive-controls-panel .node small { display:block; color:var(--secondary-text-color); font-size:12px; overflow:hidden; text-overflow:ellipsis; }
  predictive-controls-panel .toolbar { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  predictive-controls-panel .board { position:relative; min-height:580px; overflow:auto; background:var(--secondary-background-color); border:1px dashed var(--divider-color); border-radius:8px; }
  predictive-controls-panel .edges { position:absolute; inset:0; width:2000px; height:1200px; pointer-events:none; }
  predictive-controls-panel .edges line { stroke:var(--primary-color); stroke-width:3; opacity:.75; }
  predictive-controls-panel .node { position:absolute; width:180px; min-height:56px; text-align:left; cursor:grab; box-shadow:var(--ha-card-box-shadow, none); }
  predictive-controls-panel .node.selected { outline:3px solid var(--primary-color); }
  predictive-controls-panel .inspector label, predictive-controls-panel .settings label { display:block; margin-bottom:12px; }
  predictive-controls-panel .maintenance-section { margin-top:20px; padding-top:16px; border-top:1px solid var(--divider-color); }
  predictive-controls-panel .chips { display:flex; flex-wrap:wrap; gap:8px; }
  predictive-controls-panel textarea { min-height:520px; font-family:monospace; resize:vertical; }
  predictive-controls-panel textarea.small { min-height:96px; }
  predictive-controls-panel .occupancy-layout, predictive-controls-panel .reliability-layout, predictive-controls-panel .activity-layout { display:grid; grid-template-columns:minmax(0, 1fr); gap:16px; }
  predictive-controls-panel .occupancy-toolbar, predictive-controls-panel .track-section, predictive-controls-panel .diagnostics-panel, predictive-controls-panel .floor-section, predictive-controls-panel .transition-section, predictive-controls-panel .reliability-summary, predictive-controls-panel .reliability-section, predictive-controls-panel .ownership-section, predictive-controls-panel .activity-metrics, predictive-controls-panel .audit-section, predictive-controls-panel .activity-empty { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .occupancy-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; }
  predictive-controls-panel .occupancy-toolbar p { margin:4px 0 0; }
  predictive-controls-panel .section-title h3 { margin:0; }
  predictive-controls-panel .section-title small { display:block; margin-top:4px; }
  predictive-controls-panel .track-list, predictive-controls-panel .reliability-list { display:grid; grid-template-columns:minmax(0, 1fr); margin-top:12px; }
  predictive-controls-panel .track-row, predictive-controls-panel .reliability-row { display:grid; gap:6px; padding:12px 0; border-top:1px solid var(--divider-color); }
  predictive-controls-panel .track-row:first-child, predictive-controls-panel .reliability-row:first-child { border-top:0; }
  predictive-controls-panel .track-row { grid-template-columns:minmax(140px, 1fr) auto minmax(200px, 2fr); align-items:center; }
  predictive-controls-panel .reliability-row { grid-template-columns:minmax(0, 1fr); }
  predictive-controls-panel .track-row div { display:grid; gap:2px; }
  predictive-controls-panel .track-row span, predictive-controls-panel .track-row small { color:var(--secondary-text-color); overflow:hidden; text-overflow:ellipsis; }
  predictive-controls-panel .track-state { text-align:right; }
  predictive-controls-panel .empty-state { margin:12px 0 0; }
  predictive-controls-panel .diagnostics-strip { display:flex; flex-wrap:wrap; gap:8px; }
  predictive-controls-panel .diagnostics-strip span { border:1px solid var(--divider-color); border-radius:999px; padding:4px 8px; }
  predictive-controls-panel .diagnostics-list { display:grid; gap:8px; margin-top:12px; }
  predictive-controls-panel .diagnostics-list p { margin:0; display:grid; gap:2px; }
  predictive-controls-panel .diagnostics-list span { color:var(--secondary-text-color); }
  predictive-controls-panel .section-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
  predictive-controls-panel .section-head small { color:var(--secondary-text-color); }
  predictive-controls-panel .reliability-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:1px; background:var(--divider-color); }
  predictive-controls-panel .reliability-metrics div { display:grid; gap:4px; padding:14px; background:var(--card-background-color); }
  predictive-controls-panel .reliability-metrics strong { font-size:24px; }
  predictive-controls-panel .reliability-metrics span, predictive-controls-panel .reliability-summary p, predictive-controls-panel .reliability-row p, predictive-controls-panel .reliability-row small { color:var(--secondary-text-color); }
  predictive-controls-panel .reliability-summary p, predictive-controls-panel .reliability-row p { margin:10px 0 0; }
  predictive-controls-panel .reliability-row-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
  predictive-controls-panel .reliability-row-head strong { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  predictive-controls-panel .reliability-row-head span { border:1px solid var(--warning-color, #f2a900); border-radius:999px; padding:3px 8px; white-space:nowrap; }
  predictive-controls-panel .ownership-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap:1px; margin-top:14px; background:var(--divider-color); }
  predictive-controls-panel .ownership-row { min-width:0; padding:14px; background:var(--card-background-color); border-left:4px solid var(--disabled-text-color); }
  predictive-controls-panel .ownership-row.is-active { border-left-color:var(--success-color, #43a047); }
  predictive-controls-panel .ownership-name { display:flex; align-items:center; gap:9px; }
  predictive-controls-panel .ownership-name div { min-width:0; display:grid; gap:2px; }
  predictive-controls-panel .ownership-name strong, predictive-controls-panel .ownership-name small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  predictive-controls-panel .ownership-name small, predictive-controls-panel .ownership-row p, predictive-controls-panel .ownership-probabilities { color:var(--secondary-text-color); }
  predictive-controls-panel .state-indicator { width:9px; height:9px; flex:0 0 auto; border-radius:50%; background:var(--disabled-text-color); }
  predictive-controls-panel .is-active .state-indicator { background:var(--success-color, #43a047); box-shadow:0 0 0 4px color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); }
  predictive-controls-panel .ownership-row p { min-height:2.7em; margin:10px 0; line-height:1.35; }
  predictive-controls-panel .ownership-probabilities { display:flex; flex-wrap:wrap; gap:6px 12px; font-size:12px; }
  predictive-controls-panel .activity-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:1px; background:var(--divider-color); }
  predictive-controls-panel .activity-metrics div { display:grid; gap:4px; padding:14px; background:var(--card-background-color); }
  predictive-controls-panel .activity-metrics strong { font-size:22px; }
  predictive-controls-panel .activity-metrics span, predictive-controls-panel .activity-metrics p { color:var(--secondary-text-color); }
  predictive-controls-panel .activity-metrics p { grid-column:1 / -1; margin:0; padding:12px 14px; background:var(--card-background-color); }
  predictive-controls-panel .audit-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
  predictive-controls-panel .activity-filters { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }
  predictive-controls-panel .activity-filters button { padding:6px 9px; }
  predictive-controls-panel .audit-list { margin-top:12px; }
  predictive-controls-panel .audit-row { display:grid; grid-template-columns:14px minmax(0, 1fr); gap:12px; padding:14px 0; border-top:1px solid var(--divider-color); }
  predictive-controls-panel .audit-row:first-child { border-top:0; }
  predictive-controls-panel .audit-marker { width:10px; height:10px; margin-top:5px; border-radius:50%; background:var(--disabled-text-color); }
  predictive-controls-panel .kind-edges .audit-marker { background:var(--primary-color); }
  predictive-controls-panel .kind-rejected .audit-marker { background:var(--warning-color, #f2a900); }
  predictive-controls-panel .kind-observations .audit-marker { background:var(--info-color, #4797ff); }
  predictive-controls-panel .audit-content { min-width:0; }
  predictive-controls-panel .audit-row-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
  predictive-controls-panel .audit-row-head div { min-width:0; display:flex; flex-wrap:wrap; gap:5px 10px; }
  predictive-controls-panel .audit-row-head span, predictive-controls-panel .audit-row-head time, predictive-controls-panel .audit-content p, predictive-controls-panel .audit-meta { color:var(--secondary-text-color); }
  predictive-controls-panel .audit-row-head time { flex:0 0 auto; font-size:12px; }
  predictive-controls-panel .audit-content p { margin:7px 0 9px; }
  predictive-controls-panel .audit-meta { display:flex; flex-wrap:wrap; gap:6px 12px; font-size:12px; }
  predictive-controls-panel .context-badge { border:1px solid var(--divider-color); border-radius:999px; padding:2px 7px; }
  predictive-controls-panel .show-more { width:100%; margin-top:10px; }
  predictive-controls-panel .activity-empty h3 { margin-top:0; }
  predictive-controls-panel .floor-section, predictive-controls-panel .transition-section { overflow:auto; }
  predictive-controls-panel .occupancy-graph-section h3 { margin-top:0; }
  predictive-controls-panel .graph-section-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
  predictive-controls-panel .graph-summary { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
  predictive-controls-panel .graph-summary span { border:1px solid var(--divider-color); border-radius:999px; padding:4px 8px; white-space:nowrap; }
  predictive-controls-panel .graph-legend { display:flex; flex-wrap:wrap; gap:16px; margin:12px 0; color:var(--secondary-text-color); font-size:12px; }
  predictive-controls-panel .graph-legend span { display:flex; align-items:center; gap:7px; }
  predictive-controls-panel .legend-line { display:inline-block; width:28px; height:0; border-top:3px solid var(--primary-color); }
  predictive-controls-panel .legend-line.frontier { border-top-style:dashed; opacity:.8; }
  predictive-controls-panel .legend-line.authorized { border-top-color:var(--success-color, #43a047); border-top-width:5px; }
  predictive-controls-panel .legend-zone { display:inline-block; width:18px; height:12px; border:2px solid var(--divider-color); border-radius:2px; }
  predictive-controls-panel .legend-zone.warning { border-color:#d32f2f; background:color-mix(in srgb, #d32f2f 12%, var(--card-background-color)); }
  predictive-controls-panel .occupancy-board { position:relative; overflow:auto; background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:8px; }
  predictive-controls-panel .occupancy-graph { background:var(--secondary-background-color); }
  predictive-controls-panel .floor-band { position:absolute; left:12px; box-sizing:border-box; border:1px solid color-mix(in srgb, var(--divider-color) 78%, transparent); border-radius:8px; background:color-mix(in srgb, var(--card-background-color) 10%, transparent); pointer-events:none; }
  predictive-controls-panel .floor-band span { position:absolute; left:12px; top:10px; color:var(--primary-text-color); font-size:13px; font-weight:700; }
  predictive-controls-panel .zone-edges { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
  predictive-controls-panel .zone-edges line { stroke:var(--primary-color); stroke-width:3; opacity:.5; }
  predictive-controls-panel .zone-edges .frontier-edge { stroke-dasharray:10 8; stroke-width:4; opacity:.9; }
  predictive-controls-panel .zone-edges .authorized-path { stroke:var(--success-color, #43a047); stroke-width:7; opacity:.95; }
  predictive-controls-panel .zone-edges marker path { fill:var(--success-color, #43a047); }
  predictive-controls-panel .zone-card { position:absolute; box-sizing:border-box; border:1px solid var(--divider-color); border-left-width:6px; border-radius:8px; padding:12px; background:var(--card-background-color); box-shadow:var(--ha-card-box-shadow, none); z-index:1; overflow-wrap:anywhere; }
  predictive-controls-panel .zone-card.is-active { box-shadow:0 0 0 2px color-mix(in srgb, var(--success-color, #43a047) 42%, transparent), var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.has-frontier { outline:2px dashed var(--primary-color); outline-offset:3px; }
  predictive-controls-panel .zone-card-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
  predictive-controls-panel .zone-card-head strong, predictive-controls-panel .zone-card small { overflow:hidden; text-overflow:ellipsis; }
  predictive-controls-panel .zone-card-head strong { min-width:0; line-height:1.5; }
  predictive-controls-panel .zone-card-head > span { flex:0 0 auto; font-size:12px; }
  predictive-controls-panel .zone-card small { display:block; margin-top:6px; color:var(--secondary-text-color); }
  predictive-controls-panel .zone-belief-state { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:8px; flex-wrap:wrap; }
  predictive-controls-panel .zone-belief-state span { color:var(--secondary-text-color); font-size:12px; }
  predictive-controls-panel .path-frontier-label { color:var(--primary-color) !important; }
  predictive-controls-panel .zone-warning-label { color:#d32f2f !important; font-weight:700; }
  predictive-controls-panel .confidence-bar { height:8px; margin-top:10px; border-radius:999px; background:var(--divider-color); overflow:hidden; }
  predictive-controls-panel .confidence-bar span { display:block; height:100%; background:var(--primary-color); }
  predictive-controls-panel .status-rejected { border-left-color:var(--disabled-text-color); }
  predictive-controls-panel .status-suspect { border-left-color:var(--warning-color, #f2a900); }
  predictive-controls-panel .status-possible { border-left-color:var(--info-color, #4797ff); }
  predictive-controls-panel .status-probable { border-left-color:var(--success-color, #43a047); }
  predictive-controls-panel .status-confirmed { border-left-color:var(--primary-color); }
  predictive-controls-panel .transition-table { width:100%; border-collapse:collapse; margin-top:12px; }
  predictive-controls-panel .transition-table th, predictive-controls-panel .transition-table td { text-align:left; border-top:1px solid var(--divider-color); padding:10px 8px; vertical-align:top; overflow-wrap:anywhere; }
  predictive-controls-panel .transition-table th { color:var(--secondary-text-color); font-weight:600; }
  predictive-controls-panel .transition-table small { display:block; color:var(--secondary-text-color); margin-top:2px; }

  predictive-controls-panel .path-list-section { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .path-list-section h3 { margin-top:0; }
  predictive-controls-panel .selected-paths { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:16px; min-width:0; }
  predictive-controls-panel .selected-paths h3 { margin-top:0; }
  predictive-controls-panel .selected-paths .path-slot { font-weight:400; border-top:1px solid var(--divider-color); padding:12px 0; }
  predictive-controls-panel .path-slot h4 { margin:0 0 8px; font-size:13px; }
  predictive-controls-panel .path-overlap { margin:12px 0; padding:12px; border:1px solid var(--divider-color); border-radius:6px; min-width:0; }
  predictive-controls-panel .path-overlap > small { display:block; margin-top:8px; color:var(--secondary-text-color); }
  predictive-controls-panel .path-badge { display:inline-block; border:1px solid var(--divider-color); border-radius:999px; padding:3px 8px; margin-bottom:10px; font-size:12px; }
  predictive-controls-panel .path-chips { counter-reset:route; }
  predictive-controls-panel .path-chip { counter-increment:route; }
  predictive-controls-panel .path-chip::before { content:counter(route) "."; font-size:12px; }
  predictive-controls-panel [data-error]:empty, predictive-controls-panel [data-status-banner]:empty { display:none; }
  predictive-controls-panel .path-list { display:grid; gap:12px; margin:12px 0 0; padding:0; list-style:none; }
  predictive-controls-panel .path-row { display:grid; gap:10px; min-width:0; padding:12px; border:1px solid var(--divider-color); border-radius:8px; }
  predictive-controls-panel .path-row-head { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; }
  predictive-controls-panel .path-slot { font-weight:700; }
  predictive-controls-panel .path-confidence, predictive-controls-panel .path-membership { display:inline-flex; align-items:center; border:1px solid var(--divider-color); border-radius:999px; padding:3px 8px; font-size:12px; color:var(--primary-text-color); }
  predictive-controls-panel .path-confidence.confirmed { font-weight:700; }
  predictive-controls-panel .path-confidence.provisional { font-style:italic; }
  predictive-controls-panel .path-route, predictive-controls-panel .path-chips { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-width:0; margin:0; padding:0; list-style:none; }
  predictive-controls-panel .path-chip { display:inline-flex; flex-direction:column; gap:3px; min-width:0; max-width:100%; box-sizing:border-box; padding:7px 10px; border:1px solid var(--divider-color); border-radius:6px; background:var(--secondary-background-color); color:var(--primary-text-color); overflow-wrap:anywhere; }
  predictive-controls-panel .path-chip small, predictive-controls-panel .path-endpoint, predictive-controls-panel .path-eligibility, predictive-controls-panel .path-notice { color:var(--secondary-text-color); font-size:12px; overflow-wrap:anywhere; }
  predictive-controls-panel .path-arrow { color:var(--secondary-text-color); flex:0 0 auto; }
  predictive-controls-panel .path-role-label { display:block; font-weight:700; }
  predictive-controls-panel .zone-path-memberships { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
  predictive-controls-panel .zone-card .zone-warning-label, predictive-controls-panel .zone-card .path-role-label, predictive-controls-panel .zone-card .path-frontier-label, predictive-controls-panel .zone-card .path-membership { overflow:visible; white-space:normal; overflow-wrap:anywhere; }
  predictive-controls-panel .path-unavailable, predictive-controls-panel .status-error, predictive-controls-panel .status-stale, predictive-controls-panel .pc-error { padding:10px 12px; border-left:4px solid #d32f2f; color:var(--primary-text-color); background:color-mix(in srgb, #d32f2f 9%, var(--card-background-color)); overflow-wrap:anywhere; }
  predictive-controls-panel .path-legacy { padding:10px 12px; border-left:4px solid var(--warning-color, #f2a900); }

  predictive-controls-panel .zone-card.path-role-candidate, predictive-controls-panel .path-chip.path-role-candidate { border-color:var(--pc-candidate); border-style:dashed; background:color-mix(in srgb, var(--pc-candidate) 4%, var(--card-background-color)); }
  predictive-controls-panel .zone-card.path-role-history, predictive-controls-panel .path-chip.path-role-history { border:2px solid var(--pc-history); background:color-mix(in srgb, var(--pc-history) 7%, var(--card-background-color)); }
  predictive-controls-panel .zone-card.path-role-presence, predictive-controls-panel .path-chip.path-role-presence { border:2px solid var(--pc-presence); background:color-mix(in srgb, var(--pc-presence) 12%, var(--card-background-color)); font-weight:600; }
  predictive-controls-panel .zone-card.path-role-candidate { outline-color:var(--pc-candidate); box-shadow:var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.path-role-history { border-left-width:6px; outline-color:var(--pc-history); box-shadow:0 0 0 1px color-mix(in srgb, var(--pc-history) 30%, transparent), var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.path-role-presence { border-left-width:6px; outline-color:var(--pc-presence); box-shadow:0 0 0 3px color-mix(in srgb, var(--pc-presence) 40%, transparent), var(--ha-card-box-shadow, none); }
  predictive-controls-panel .zone-card.path-role-presence.has-frontier, predictive-controls-panel .zone-card.path-role-history.has-frontier { outline-style:solid; }
  predictive-controls-panel .zone-card.path-role-presence .confidence-bar span { background:var(--pc-presence); }
  predictive-controls-panel .zone-card.path-role-history .confidence-bar span { background:var(--pc-history); }
  predictive-controls-panel .zone-card.path-role-candidate .confidence-bar span { background:var(--pc-candidate); }
  predictive-controls-panel .legend-line.path-role-candidate { border-top:2px dashed var(--pc-candidate); }
  predictive-controls-panel .legend-line.path-role-history { border-top:4px solid var(--pc-history); }
  predictive-controls-panel .legend-line.path-role-presence { border-top:6px solid var(--pc-presence); }
  predictive-controls-panel .zone-edges .selected-path { fill:none; stroke:var(--pc-history); stroke-width:4; opacity:1; }
  predictive-controls-panel .zone-edges .selected-path-edge { stroke:var(--pc-history); stroke-width:5; opacity:1; }
  predictive-controls-panel .zone-edges .path-arrow { fill:none; stroke:var(--pc-history); stroke-width:4; opacity:1; }
  predictive-controls-panel .legend-line.candidate { border-top:2px dashed var(--pc-candidate); }
  predictive-controls-panel .legend-line.history { border-top:4px solid var(--pc-history); }
  predictive-controls-panel .legend-line.presence { border-top:6px solid var(--pc-presence); }
  predictive-controls-panel .zone-edges .path-role-candidate { stroke:var(--pc-candidate); stroke-width:2; stroke-dasharray:8 6; opacity:.65; }
  predictive-controls-panel .zone-edges .path-role-history { stroke:var(--pc-history); stroke-width:4; stroke-dasharray:none; opacity:.9; }
  predictive-controls-panel .zone-edges .path-role-presence { stroke:var(--pc-presence); stroke-width:6; stroke-dasharray:none; opacity:1; }
  predictive-controls-panel .zone-edges marker.path-role-presence path { fill:var(--pc-presence); }
  predictive-controls-panel .zone-edges marker.path-role-history path { fill:var(--pc-history); }

  predictive-controls-panel .zone-card.has-warning { border-color:#d32f2f; box-shadow:0 0 0 2px color-mix(in srgb, #d32f2f 52%, transparent), var(--ha-card-box-shadow, none); background:color-mix(in srgb, #d32f2f 9%, var(--card-background-color)); outline-color:#d32f2f; }
  predictive-controls-panel .zone-card.has-warning .confidence-bar span { background:#d32f2f; }
  predictive-controls-panel .path-chip.has-warning { border-color:#d32f2f; box-shadow:0 0 0 1px color-mix(in srgb, #d32f2f 52%, transparent); }
  predictive-controls-panel .zone-edges .has-warning { stroke:#d32f2f; }
  predictive-controls-panel .zone-edges marker.has-warning path { fill:#d32f2f; }

  predictive-controls-panel :is(button, input, select, textarea, a, [tabindex]):focus-visible { outline:3px solid var(--primary-color, #03a9f4); outline-offset:3px; }
  predictive-controls-panel [hidden] { display:none !important; }
  predictive-controls-panel .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; border:0; }
  predictive-controls-panel .pc-shell :is(p, h1, h2, h3, label, .section-title, .path-membership) { overflow-wrap:anywhere; }

  @media (max-width:1000px) {
    predictive-controls-panel .map-layout { grid-template-columns:minmax(0, 1fr); }
  }
  @media (max-width:700px) {
    predictive-controls-panel .pc-shell { padding:12px; }
    predictive-controls-panel header, predictive-controls-panel .occupancy-toolbar, predictive-controls-panel .audit-heading, predictive-controls-panel .graph-section-head { align-items:flex-start; flex-direction:column; }
    predictive-controls-panel .graph-summary { justify-content:flex-start; }
    predictive-controls-panel .track-row { grid-template-columns:minmax(0, 1fr) auto; }
    predictive-controls-panel .track-row small { grid-column:1 / -1; }
    predictive-controls-panel .reliability-metrics { grid-template-columns:1fr; }
    predictive-controls-panel .activity-metrics { grid-template-columns:1fr; }
    predictive-controls-panel .activity-metrics p { grid-column:1; }
    predictive-controls-panel .activity-filters { justify-content:flex-start; }
    predictive-controls-panel .audit-row-head { display:grid; }
    predictive-controls-panel .section-head, predictive-controls-panel .reliability-row-head { flex-wrap:wrap; }
    predictive-controls-panel .reliability-row-head strong, predictive-controls-panel .reliability-row-head span { white-space:normal; overflow-wrap:anywhere; }
    predictive-controls-panel .path-list-section, predictive-controls-panel .path-row { padding:12px; }
    predictive-controls-panel .entities { max-height:320px; }
    predictive-controls-panel input, predictive-controls-panel select, predictive-controls-panel textarea { font-size:16px; }
  }
  @media (forced-colors:active) {
    predictive-controls-panel .zone-card, predictive-controls-panel .path-chip { border-color:CanvasText; box-shadow:none; }
    predictive-controls-panel .zone-card.path-role-presence { border-left-width:8px; }
    predictive-controls-panel .zone-card.has-warning, predictive-controls-panel .path-chip.has-warning { border-color:LinkText; outline:2px solid LinkText; outline-offset:2px; }
    predictive-controls-panel .zone-card.has-warning .confidence-bar span { background:LinkText; }
    predictive-controls-panel .zone-edges line, predictive-controls-panel .zone-edges .selected-path { stroke:CanvasText; }
    predictive-controls-panel :is(button, input, select, textarea, a, [tabindex]):focus-visible { outline-color:Highlight; }
  }
  @media (prefers-reduced-motion:reduce) {
    predictive-controls-panel, predictive-controls-panel *, predictive-controls-panel *::before, predictive-controls-panel *::after { animation:none !important; transition:none !important; scroll-behavior:auto !important; }
  }
`;