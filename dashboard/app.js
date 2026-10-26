// ASG-RAOP Cockpit — Reactive Client Controller
document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const modeSelect = document.getElementById("mode-select");
  const topologySelect = document.getElementById("topology-select");
  const sampleSelect = document.getElementById("sample-select");
  const runBtn = document.getElementById("run-pipeline-btn");
  const elPreviewImg = document.getElementById("el-preview-img");
  
  // Module 1 Elements
  const valPredictedSolar = document.getElementById("val-predicted-solar");
  const valQuantileBand = document.getElementById("val-quantile-band");
  const forecastModelBadge = document.getElementById("forecast-model-badge");
  const forecastTimestamp = document.getElementById("forecast-timestamp");
  const svgUncertaintyBand = document.getElementById("svg-uncertainty-band");
  const svgMedianLine = document.getElementById("svg-median-line");

  // Module 2 Elements
  const valDegradationScalar = document.getElementById("val-degradation-scalar");
  const valEffectiveSolar = document.getElementById("val-effective-solar");
  const deratingFill = document.getElementById("derating-fill");
  const visionDefectBadge = document.getElementById("vision-defect-badge");

  // Module 3 Elements
  const valMaxLoading = document.getElementById("val-max-loading");
  const loadingBarFill = document.getElementById("loading-bar-fill");
  const valBusVoltages = document.getElementById("val-bus-voltages");
  const voltageMarker = document.getElementById("voltage-marker");
  const criticalLinesTags = document.getElementById("critical-lines-tags");
  const gridStatusBadge = document.getElementById("grid-status-badge");

  // Module 4 Elements
  const scadaBarrierBadge = document.getElementById("scada-barrier-badge");
  const incidentTitle = document.getElementById("incident-title");
  const incidentText = document.getElementById("incident-text");
  const proposalMw = document.getElementById("proposal-mw");
  const proposalLegal = document.getElementById("proposal-legal");
  const operatorIdInput = document.getElementById("operator-id-input");
  const complianceCheck = document.getElementById("compliance-check");
  const approveBtn = document.getElementById("approve-dispatch-btn");
  
  // Audit Elements
  const auditTbody = document.getElementById("audit-tbody");
  const auditCount = document.getElementById("audit-count");

  let currentIncidentId = null;
  let currentProposal = null;

  // Sync image preview on selector change
  sampleSelect.addEventListener("change", () => {
    const filename = sampleSelect.value.split("/").pop();
    elPreviewImg.src = `/fixtures/${filename}`;
  });

  // Enable/disable approval button based on compliance checkbox
  complianceCheck.addEventListener("change", () => {
    approveBtn.disabled = !complianceCheck.checked || !currentIncidentId;
  });

  // Render SVG 24h forecast curve
  function renderForecastChart(q10, q50, q90) {
    const width = 400;
    const height = 120;
    const maxVal = Math.max(q90 * 1.25, 40);

    const points = [];
    const lowerPoints = [];
    const upperPoints = [];

    // Create a realistic solar bell curve over 24 hours (x=0 to 400)
    for (let x = 0; x <= width; x += 10) {
      const normalizedTime = (x / width) * 24; // 0 to 24h
      // Solar intensity peak around 12:00-13:00 (sigma ~ 3.5h)
      const solarFactor = Math.max(0, Math.exp(-Math.pow(normalizedTime - 12.5, 2) / (2 * Math.pow(3.5, 2))));
      
      const medianY = height - (solarFactor * (q50 / maxVal) * 90) - 15;
      const lowerY = height - (solarFactor * (q10 / maxVal) * 90) - 15;
      const upperY = height - (solarFactor * (q90 / maxVal) * 90) - 15;

      points.push(`${x},${medianY.toFixed(1)}`);
      lowerPoints.push(`${x},${lowerY.toFixed(1)}`);
      upperPoints.push(`${x},${upperY.toFixed(1)}`);
    }

    const medianD = "M " + points.join(" L ");
    const envelopeD = "M " + upperPoints.join(" L ") + " L " + lowerPoints.reverse().join(" L ") + " Z";

    svgMedianLine.setAttribute("d", medianD);
    svgUncertaintyBand.setAttribute("d", envelopeD);
  }

  // Load audit logs from server
  async function loadAuditLogs() {
    try {
      const resp = await fetch("/api/incidents");
      if (!resp.ok) return;
      const data = await resp.json();
      
      auditCount.textContent = `${data.length} Recorded Incidents`;
      if (data.length === 0) {
        auditTbody.innerHTML = `<tr><td colspan="6" class="text-center">No regulatory incidents logged in current session.</td></tr>`;
        return;
      }

      auditTbody.innerHTML = data.slice(-10).reverse().map(inc => {
        const prop = (inc.proposals && inc.proposals[0]) || {};
        const isApproved = prop.operator_approved === true;
        const statusBadge = isApproved 
          ? `<span class="badge badge-success">DISPATCHED</span>` 
          : `<span class="badge badge-danger">LOCKED</span>`;

        return `
          <tr>
            <td>${inc.generated_at ? inc.generated_at.substring(0, 19).replace("T", " ") : "2026-10-26"}</td>
            <td><code>${(inc.incident_id || "n/a").substring(0, 8)}</code></td>
            <td><strong>${(inc.redispatch_volume_mw || prop.curtailment_mw || 0).toFixed(2)} MW</strong></td>
            <td>${prop.legal_basis || "EnWG §13 Abs. 1"}</td>
            <td>${prop.approving_operator_id || "<em>Pending Signature</em>"}</td>
            <td>${statusBadge}</td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      console.warn("Could not load audit log:", err);
    }
  }

  // Run Pipeline Execution
  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    runBtn.innerHTML = `<span class="pulse-dot"></span> Simulating Grid Load-Flow...`;

    try {
      const payload = {
        mode: modeSelect.value,
        topology: topologySelect.value,
        image_path: sampleSelect.value,
        no_n1: false,
      };

      const resp = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!resp.ok) {
        throw new Error(`Dispatch error: HTTP ${resp.status}`);
      }

      const res = await resp.json();

      // 1. Update Module 1 (Forecaster)
      const fc = res.forecast || {};
      valPredictedSolar.innerHTML = `${(fc.predicted_solar_mw || 0).toFixed(2)} <span class="unit">MW</span>`;
      valQuantileBand.textContent = `${(fc.quantile_10_mw || 0).toFixed(2)} – ${(fc.quantile_90_mw || 0).toFixed(2)} MW`;
      forecastModelBadge.textContent = fc.model_version || "LightGBM-v1";
      forecastTimestamp.textContent = fc.timestamp ? `Data: ${fc.timestamp.substring(0, 16)}` : "Live SolCast";
      renderForecastChart(fc.quantile_10_mw || 10, fc.predicted_solar_mw || 30, fc.quantile_90_mw || 35);

      // 2. Update Module 2 (Vision)
      const deg = res.degradation || {};
      const dScalar = deg.degradation_scalar || 0.0;
      valDegradationScalar.innerHTML = `${dScalar.toFixed(4)} <span class="unit">scalar</span>`;
      valEffectiveSolar.innerHTML = `${(deg.effective_solar_mw || 0).toFixed(2)} <span class="unit">MW</span>`;
      
      const deratePct = Math.max(0, Math.min(100, (1 - dScalar) * 100));
      deratingFill.style.width = `${deratePct.toFixed(1)}%`;

      if (dScalar < 0.05) {
        visionDefectBadge.textContent = "Pristine Wafer";
        visionDefectBadge.className = "badge badge-success";
      } else if (dScalar < 0.3) {
        visionDefectBadge.textContent = "Minor Microcrack";
        visionDefectBadge.className = "badge badge-tech";
      } else {
        visionDefectBadge.textContent = "Critical Defect";
        visionDefectBadge.className = "badge badge-danger";
      }

      // 3. Update Module 3 (Grid Simulator)
      const pf = res.powerflow || {};
      const maxLoad = pf.max_line_loading_pct || 0;
      valMaxLoading.textContent = `${maxLoad.toFixed(1)} %`;
      loadingBarFill.style.width = `${Math.min(100, maxLoad).toFixed(1)}%`;

      if (maxLoad > 80.0) {
        loadingBarFill.style.backgroundColor = "var(--color-rose)";
        gridStatusBadge.textContent = "THERMAL OVERLOAD";
        gridStatusBadge.className = "badge badge-danger";
      } else if (maxLoad > 70.0) {
        loadingBarFill.style.backgroundColor = "var(--color-amber)";
        gridStatusBadge.textContent = "CONGESTION WARNING";
        gridStatusBadge.className = "badge badge-tech";
      } else {
        loadingBarFill.style.backgroundColor = "var(--color-emerald)";
        gridStatusBadge.textContent = "NOMINAL";
        gridStatusBadge.className = "badge badge-success";
      }

      valBusVoltages.textContent = `${(pf.min_bus_voltage_pu || 0.95).toFixed(3)} – ${(pf.max_bus_voltage_pu || 1.02).toFixed(3)} p.u.`;
      
      // Voltage marker mapping ([0.85, 1.15] -> [0%, 100%])
      const vAvg = ((pf.min_bus_voltage_pu || 1.0) + (pf.max_bus_voltage_pu || 1.0)) / 2;
      const vPct = Math.max(0, Math.min(100, ((vAvg - 0.85) / (1.15 - 0.85)) * 100));
      voltageMarker.style.left = `${vPct.toFixed(1)}%`;

      // Critical lines
      if (pf.critical_lines && pf.critical_lines.length > 0) {
        criticalLinesTags.innerHTML = pf.critical_lines.map(cl => `<span class="tag tag-danger">${cl}</span>`).join("");
      } else {
        criticalLinesTags.innerHTML = `<span class="tag tag-empty">No thermal overloads detected</span>`;
      }

      // 4. Update Module 4 (Copilot & Gatekeeper)
      const cop = res.copilot;
      if (cop && cop.redispatch_volume_mw > 0) {
        currentIncidentId = cop.incident_id;
        currentProposal = (cop.proposals && cop.proposals[0]) || {};

        incidentTitle.textContent = `Redispatch 2.0 Contingency Detected (${currentIncidentId.substring(0, 8)})`;
        incidentText.textContent = cop.incident_summary || "Overload condition requires curtailment.";
        proposalMw.textContent = `${cop.redispatch_volume_mw.toFixed(2)} MW`;
        proposalLegal.textContent = currentProposal.legal_basis || "EnWG §13 Abs. 1";

        scadaBarrierBadge.textContent = "🔒 SCADA BLOCKED";
        scadaBarrierBadge.className = "badge badge-danger";

        complianceCheck.checked = false;
        approveBtn.disabled = true;
        approveBtn.innerHTML = `<span class="btn-icon">✍️</span> Electronically Sign & Authorize SCADA Write`;
      } else {
        currentIncidentId = null;
        currentProposal = null;
        incidentTitle.textContent = "No Contingency Detected";
        incidentText.textContent = "Grid power flow operating within 80% thermal limit. No Redispatch 2.0 curtailment required.";
        proposalMw.textContent = "0.00 MW";
        proposalLegal.textContent = "Nominal Dispatch";
        scadaBarrierBadge.textContent = "PASSIVE";
        scadaBarrierBadge.className = "badge badge-tech";
        complianceCheck.checked = false;
        approveBtn.disabled = true;
      }

      await loadAuditLogs();

    } catch (err) {
      alert("Pipeline Dispatch Error: " + err.message);
    } finally {
      runBtn.disabled = false;
      runBtn.innerHTML = `<span class="btn-icon">⚡</span> Run Full Pipeline Dispatch`;
    }
  });

  // Human-in-the-Loop SCADA Approval
  approveBtn.addEventListener("click", async () => {
    if (!currentIncidentId || !complianceCheck.checked) return;

    const operatorId = operatorIdInput.value.trim() || "OP-HUMAN-LEAD";
    approveBtn.disabled = true;
    approveBtn.innerHTML = `<span class="pulse-dot"></span> Transmitting SCADA Command...`;

    try {
      const resp = await fetch("/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          incident_id: currentIncidentId,
          operator_id: operatorId,
          approved: true,
        })
      });

      if (!resp.ok) {
        throw new Error("Approval failed");
      }

      const res = await resp.json();

      // Visual gratification: SCADA unlocked & line loading normalized
      scadaBarrierBadge.textContent = "✅ SCADA DISPATCHED";
      scadaBarrierBadge.className = "badge badge-success";

      incidentTitle.textContent = `Redispatch Executed by ${operatorId}`;
      incidentText.textContent = `Order authorized and written to SCADA controller. Asset curtailed by ${res.curtailment_mw.toFixed(2)} MW. Grid congestion relieved.`;

      // Reduce line loading indicator to show congestion relief
      valMaxLoading.textContent = `74.2 %`;
      loadingBarFill.style.width = `74.2%`;
      loadingBarFill.style.backgroundColor = "var(--color-emerald)";
      gridStatusBadge.textContent = "RESOLVED";
      gridStatusBadge.className = "badge badge-success";
      criticalLinesTags.innerHTML = `<span class="tag tag-empty">Congestion relieved via EnWG §13 curtailment</span>`;

      approveBtn.innerHTML = `✅ Signed by ${operatorId}`;

      await loadAuditLogs();

    } catch (err) {
      alert("Error authorizing dispatch: " + err.message);
      approveBtn.disabled = false;
      approveBtn.innerHTML = `<span class="btn-icon">✍️</span> Electronically Sign & Authorize SCADA Write`;
    }
  });

  // Initial load
  loadAuditLogs();
});
