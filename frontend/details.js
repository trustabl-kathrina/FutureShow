const API_BASE = location.origin.replace(/\/$/, "");
const loader = document.getElementById("detailLoader");
const errorEl = document.getElementById("detailError");
const contentEl = document.getElementById("detailContent");
const titleEl = document.getElementById("detailTitle");
const slugEl = document.getElementById("detailSlug");
const metaGrid = document.getElementById("detailMeta");
const latestModelsEl = document.getElementById("latestModels");
const historyListEl = document.getElementById("historyList");
const backButton = document.getElementById("backButton");
const chartsSection = document.getElementById("chartsSection");
const priceChartCanvas = document.getElementById("priceChart");
const distributionChartCanvas = document.getElementById("distributionChart");
const groundTruthBanner = document.getElementById("groundTruthBanner");
const groundTruthValue = document.getElementById("groundTruthValue");

let priceChartInstance = null;
let distributionChartInstance = null;

const params = new URLSearchParams(window.location.search);
const slug = params.get("slug");

const numberFormatter = new Intl.NumberFormat("en-US");

function setLoading(show) {
  if (!loader) return;
  loader.classList.toggle("hidden", !show);
}

function showError(message) {
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.classList.remove("hidden");
  }
  if (contentEl) contentEl.classList.add("hidden");
}

async function fetchDetails() {
  if (!slug) {
    setLoading(false);
    showError("No event slug provided.");
    return;
  }

  try {
    setLoading(true);
    const resp = await fetch(`${API_BASE}/api/predictions/${encodeURIComponent(slug)}`);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "Failed to fetch details");
    renderDetails(data.event || {});
  } catch (err) {
    console.error("Failed to fetch detail", err);
    showError("Failed to load. Please try again later.");
  } finally {
    setLoading(false);
  }
}

function renderDetails(event) {
  if (errorEl) errorEl.classList.add("hidden");
  if (contentEl) contentEl.classList.remove("hidden");

  titleEl.textContent = event.title || slug;
  const desc = event.description ? truncate(event.description, 280) : "";
  slugEl.textContent = desc ? `${slug} · ${desc}` : slug;

  renderMeta(event);
  renderCharts(event);
  renderLatest(event.history || [], event.model_stats || {});
  renderHistory(event.history || [], event.model_stats || {});
}

function renderMeta(event) {
  metaGrid.innerHTML = "";
  const cards = [];
  const marketInfo = event.market_info || {};
  const info = marketInfo.info || {};

  if (typeof marketInfo.probability === "number") {
    cards.push(createMetaCard("Market Probability", `${Math.round(marketInfo.probability * 100)}%`));
  }

  const closed = info.closed || Boolean(event.result);
  cards.push(createMetaCard("Status", closed ? "Closed" : "Live"));

  if (info.volume !== undefined) {
    cards.push(createMetaCard("Volume", `$${numberFormatter.format(Math.round(Number(info.volume)))}`));
  }

  if (event.category) {
    cards.push(createMetaCard("Category", event.category));
  }

  if (event.endDate) {
    cards.push(createMetaCard("End Date", formatDate(event.endDate)));
  }

  if (event.result && typeof event.result === "object") {
    const resolution = event.result.resolution || event.result.status || "Resolved";
    cards.push(createMetaCard("Result", resolution));
  }

  const accuracy = computeAccuracySummary(event.model_stats || {});
  const accValue = accuracy ? `${accuracy.correct}/${accuracy.total}` : "0/0";
  const accSub = accuracy ? `${accuracy.pct}% success` : "0% success";
  cards.push(createMetaCard("Accuracy", accValue, accSub));

  if (!cards.length) {
    metaGrid.innerHTML = `<div class="meta-card"><div class="meta-label">Info</div><div class="meta-value">No metadata available</div></div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  cards.forEach(card => frag.appendChild(card));
  metaGrid.appendChild(frag);
  
  // Show ground truth for closed events
  renderGroundTruth(event);
}

function renderGroundTruth(event) {
  if (!groundTruthBanner || !groundTruthValue) return;
  
  // Use gt_id from backend (same as card display)
  const gtId = event.gt_id;
  
  if (gtId) {
    groundTruthValue.textContent = gtId;
    groundTruthBanner.classList.remove("hidden");
  } else {
    groundTruthBanner.classList.add("hidden");
  }
}

function createMetaCard(label, value, sub) {
  const card = document.createElement("div");
  card.className = "meta-card";

  const labelEl = document.createElement("div");
  labelEl.className = "meta-label";
  labelEl.textContent = label;

  const valueEl = document.createElement("div");
  valueEl.className = "meta-value";
  valueEl.textContent = value || "--";

  card.append(labelEl, valueEl);

  if (sub) {
    const subEl = document.createElement("div");
    subEl.className = "meta-sub";
    subEl.textContent = sub;
    card.append(subEl);
  }

  return card;
}

function renderLatest(history, eventModelStats) {
  latestModelsEl.innerHTML = "";
  if (!history.length) {
    latestModelsEl.innerHTML = `<div class="empty-state">No predictions yet.</div>`;
    return;
  }

  const latestMap = new Map();
  history.forEach(entry => {
    const key = entry.model || entry.signature || "unknown";
    const existing = latestMap.get(key);
    if (!existing || new Date(entry.timestamp || 0) > new Date(existing.timestamp || 0)) {
      latestMap.set(key, entry);
    }
  });

  const cards = Array.from(latestMap.values()).sort(
    (a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)
  );

  const frag = document.createDocumentFragment();
  cards.forEach(entry => {
    const card = document.createElement("div");
    card.className = "model-card";

    const header = document.createElement("div");
    header.className = "model-header";
    header.textContent = entry.model || "Unknown";

    const call = (entry.parsed_call || "ABSTAIN").toUpperCase();
    const callEl = document.createElement("div");
    callEl.className = "model-call";
    callEl.textContent = call;

    const resultBadge = createResultBadge(entry);
    if (resultBadge) {
      callEl.append(" ", resultBadge);
    }
    const accBadge = createAccuracyBadge(entry.model, eventModelStats);
    if (accBadge) {
      callEl.append(" ", accBadge);
    }

    const selectionEl = document.createElement("div");
    selectionEl.className = "model-selection";
    const firstPrediction = (entry.prediction_details || [])[0];
    selectionEl.textContent = firstPrediction
      ? firstPrediction.market_selection || firstPrediction.market_question || firstPrediction.market_slug || ""
      : "";

    const probText = formatProbabilityBadge(entry);
    if (probText) {
      const badge = document.createElement("span");
      badge.className = "prob-badge";
      badge.textContent = probText;
      callEl.append(" ", badge);
    }

    const previewEl = document.createElement("div");
    previewEl.className = "forecast-text";
    const fullText = entry.forecast_full || entry.forecast || "";
    const previewText = truncate(fullText, 220);
    const hasFullText = Boolean(fullText && previewText !== fullText);
    previewEl.textContent = previewText;

    const timeEl = document.createElement("div");
    timeEl.className = "forecast-time";
    timeEl.textContent = formatDate(entry.timestamp);

    card.append(header, callEl);
    if (selectionEl.textContent) card.append(selectionEl);
    card.append(previewEl);
    if (hasFullText) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "forecast-toggle";
      toggle.textContent = "Show Full Text";
      toggle.dataset.expanded = "false";
      toggle.addEventListener("click", () => {
        const expanded = toggle.dataset.expanded === "true";
        if (expanded) {
          previewEl.textContent = previewText;
          toggle.textContent = "Show Full Text";
          toggle.dataset.expanded = "false";
        } else {
          previewEl.textContent = fullText;
          toggle.textContent = "Collapse";
          toggle.dataset.expanded = "true";
        }
      });
      card.append(toggle);
    }
    card.append(timeEl);
    frag.appendChild(card);
  });

  latestModelsEl.appendChild(frag);
}

function renderHistory(history, eventModelStats) {
  historyListEl.innerHTML = "";
  if (!history.length) {
    historyListEl.innerHTML = `<div class="empty-state">No history records.</div>`;
    return;
  }

  const reversed = [...history].reverse();
  const frag = document.createDocumentFragment();

  reversed.forEach(entry => {
    const card = document.createElement("div");
    card.className = "forecast-card";

    const header = document.createElement("div");
    header.className = "forecast-header";

    const meta = document.createElement("div");
    meta.className = "forecast-meta";

    const modelEl = document.createElement("div");
    modelEl.className = "model-name";
    modelEl.textContent = entry.model || "Unknown";

    const tsEl = document.createElement("div");
    tsEl.className = "forecast-time";
    tsEl.textContent = formatDate(entry.timestamp);

    meta.append(modelEl, tsEl);

    const actions = document.createElement("div");
    actions.className = "forecast-actions";

    const callBadge = document.createElement("span");
    callBadge.className = callClass(entry.parsed_call);
    callBadge.textContent = (entry.parsed_call || "ABSTAIN").toUpperCase();
    actions.append(callBadge);

    const resultBadge = createResultBadge(entry);
    if (resultBadge) {
      actions.append(resultBadge);
    }
    const accBadge = createAccuracyBadge(entry.model, eventModelStats);
    if (accBadge) {
      actions.append(accBadge);
    }

    const probText = formatProbabilityBadge(entry);
    if (probText) {
      const probBadge = document.createElement("span");
      probBadge.className = "prob-badge";
      probBadge.textContent = probText;
      actions.append(probBadge);
    }

    header.append(meta, actions);
    card.append(header);

    const details = entry.prediction_details || [];
    if (details.length) {
      const chips = document.createElement("div");
      chips.className = "forecast-actions";
      details.forEach(detail => {
        const chip = document.createElement("span");
        chip.className = "market-chip";
        const label =
          detail.market_selection ||
          detail.market_question ||
          detail.market_slug ||
          "Market";
        chip.textContent = `${label} · ${(detail.outcome || entry.parsed_call || "").toUpperCase()}`;
        chips.append(chip);
      });
      card.append(chips);
    }

    const textEl = document.createElement("div");
    textEl.className = "forecast-text";
    const previewText = entry.forecast || "";
    const fullText = entry.forecast_full || "";
    const hasFullText = Boolean(fullText && fullText !== previewText);
    let truncatedNote = null;
    if (entry.forecast_truncated || hasFullText) {
      truncatedNote = document.createElement("div");
      truncatedNote.className = "truncated-note";
      truncatedNote.textContent = hasFullText
        ? "Truncated. Click to expand full text."
        : "Forecast truncated for display; see data/forecasts for the full text.";
    }
    textEl.textContent = previewText;
    card.append(textEl);

    if (hasFullText) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "forecast-toggle";
      toggle.textContent = "Show Full Text";
      toggle.dataset.expanded = "false";
      toggle.addEventListener("click", () => {
        const expanded = toggle.dataset.expanded === "true";
        if (expanded) {
          textEl.textContent = previewText;
          toggle.textContent = "Show Full Text";
          toggle.dataset.expanded = "false";
          if (truncatedNote) {
            truncatedNote.textContent = "Truncated. Click to expand full text.";
          }
        } else {
          textEl.textContent = fullText;
          toggle.textContent = "Collapse";
          toggle.dataset.expanded = "true";
          if (truncatedNote) {
            truncatedNote.textContent = "Full text expanded. Click to collapse.";
          }
        }
      });
      card.append(toggle);
    }

    if (truncatedNote) {
      card.append(truncatedNote);
    }

    frag.appendChild(card);
  });

  historyListEl.appendChild(frag);
}

function callClass(call) {
  const normalized = (call || "").toString().toUpperCase();
  if (normalized.includes("YES")) return "pill yes";
  if (normalized.includes("NO")) return "pill no";
  return "pill abstain";
}

function createResultBadge(entry) {
  if (!entry) return null;
  const success = typeof entry.success === "boolean" ? entry.success : null;
  const resolved = entry.resolved_outcome || null;
  if (success === null && !resolved) return null;

  const badge = document.createElement("span");
  let cls = "result-badge";
  if (success === true) cls += " result-success";
  else if (success === false) cls += " result-failed";
  badge.className = cls;

  const parts = [];
  if (success === true) parts.push("WIN");
  else if (success === false) parts.push("LOSS");
  if (resolved) parts.push(`Resolved: ${resolved}`);

  badge.textContent = parts.join(" · ") || "Resolved";
  return badge;
}

function createAccuracyBadge(modelName, eventModelStats) {
  if (!modelName) return null;
  const stats = eventModelStats && eventModelStats[modelName];
  if (!stats || !stats.total) return null;
  const accPct = Math.round((stats.correct / stats.total) * 100);
  const badge = document.createElement("span");
  badge.className = "prob-badge";
  badge.textContent = `Event Acc: ${stats.correct}/${stats.total} (${accPct}%)`;
  return badge;
}

function computeAccuracySummary(stats) {
  if (!stats || typeof stats !== "object") return null;
  let total = 0;
  let correct = 0;
  Object.values(stats).forEach(entry => {
    if (!entry || typeof entry !== "object") return;
    if (typeof entry.total === "number") total += entry.total;
    if (typeof entry.correct === "number") correct += entry.correct;
  });
  if (!total) return null;
  const pct = Math.round((correct / total) * 100);
  return { total, correct, pct };
}

function formatProbabilityBadge(entry) {
  const prob = entry.market_prob;
  if (!prob || typeof prob !== "object") return "";
  const call = (entry.parsed_call || "").toUpperCase();
  const yes = typeof prob.yes_prob === "number" ? Math.round(prob.yes_prob * 100) : null;
  const no = typeof prob.no_prob === "number" ? Math.round(prob.no_prob * 100) : null;

  if (call.includes("YES") && yes !== null) return `YES ${yes}%`;
  if (call.includes("NO") && no !== null) return `NO ${no}%`;
  if (yes !== null && no !== null) return `YES ${yes}% · NO ${no}%`;
  if (yes !== null) return `YES ${yes}%`;
  if (no !== null) return `NO ${no}%`;
  return "";
}

function formatDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function truncate(value, limit) {
  if (!value) return "";
  if (value.length <= limit) return value;
  return `${value.slice(0, limit).trim()}…`;
}

// Chart color palette matching the theme
const CHART_COLORS = [
  "#00d4ff", // cyan (primary accent)
  "#7c3aed", // purple (secondary accent)
  "#10b981", // green (success)
  "#f59e0b", // amber (warning)
  "#ef4444", // red (danger)
  "#6366f1", // indigo
  "#ec4899", // pink
  "#14b8a6", // teal
];

// Model colors for bar chart
const MODEL_COLORS = {
  "gemini-2.5-pro": "#4285f4",
  "gemini-3-flash": "#4285f4",
  "gemini-3-flash-preview": "#4285f4",
  "claude-4.5-sonnet": "#d97757",
  "gpt-5": "#10a37f",
  "deepseek-v3.1": "#7c3aed"
};

function renderCharts(event) {
  const isClosed = Boolean(event.result);
  const priceHistory = event.price_history;
  const predictionDistribution = event.prediction_distribution;
  
  // Only show charts section for closed events with data
  const hasPriceHistory = priceHistory && Object.keys(priceHistory).length > 0;
  const hasDistribution = predictionDistribution && Object.keys(predictionDistribution).length > 0;
  
  if (!isClosed || (!hasPriceHistory && !hasDistribution)) {
    if (chartsSection) chartsSection.classList.add("hidden");
    return;
  }
  
  if (chartsSection) chartsSection.classList.remove("hidden");
  
  // Render both charts
  renderPriceChart(priceHistory);
  renderDistributionChart(predictionDistribution);
}

function renderPriceChart(priceHistory) {
  // Destroy existing chart if any
  if (priceChartInstance) {
    priceChartInstance.destroy();
    priceChartInstance = null;
  }
  
  if (!priceChartCanvas || !priceHistory) return;
  
  // Build datasets for each market
  const datasets = [];
  const marketSlugs = Object.keys(priceHistory);
  
  marketSlugs.forEach((marketSlug, index) => {
    const marketData = priceHistory[marketSlug];
    const outcome = marketData.outcome || "Yes";
    const dataPoints = marketData.data || [];
    
    if (dataPoints.length === 0) return;
    
    const color = CHART_COLORS[index % CHART_COLORS.length];
    
    // Create label: use outcome for single market, market slug for multiple
    let label = outcome;
    if (marketSlugs.length > 1) {
      // Shorten market slug for display
      const shortSlug = marketSlug.length > 30 
        ? marketSlug.substring(0, 27) + "..." 
        : marketSlug;
      label = `${shortSlug} (${outcome})`;
    }
    
    datasets.push({
      label: label,
      data: dataPoints.map(d => ({
        x: new Date(d.timestamp),
        y: d.price
      })),
      borderColor: color,
      backgroundColor: color + "20", // 12% opacity
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.1,
      fill: false
    });
  });
  
  if (datasets.length === 0) return;
  
  // Get CSS variables for theming
  const styles = getComputedStyle(document.documentElement);
  const textColor = styles.getPropertyValue("--text-secondary").trim() || "#8ba3b8";
  const gridColor = styles.getPropertyValue("--border-subtle").trim() || "rgba(0, 212, 255, 0.08)";
  
  priceChartInstance = new Chart(priceChartCanvas, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false
      },
      plugins: {
        legend: {
          display: datasets.length > 1,
          position: "top",
          labels: {
            color: textColor,
            font: {
              family: "'JetBrains Mono', monospace",
              size: 11
            },
            boxWidth: 12,
            padding: 16
          }
        },
        tooltip: {
          backgroundColor: "rgba(13, 18, 32, 0.95)",
          titleColor: "#e8f4f8",
          bodyColor: "#8ba3b8",
          borderColor: "rgba(0, 212, 255, 0.3)",
          borderWidth: 1,
          padding: 12,
          titleFont: {
            family: "'JetBrains Mono', monospace",
            size: 11
          },
          bodyFont: {
            family: "'Inter', sans-serif",
            size: 12
          },
          callbacks: {
            title: function(context) {
              const date = new Date(context[0].parsed.x);
              return date.toLocaleString();
            },
            label: function(context) {
              const value = (context.parsed.y * 100).toFixed(1);
              return `${context.dataset.label}: ${value}%`;
            }
          }
        }
      },
      scales: {
        x: {
          type: "time",
          time: {
            displayFormats: {
              hour: "MMM d, HH:mm",
              day: "MMM d",
              week: "MMM d"
            }
          },
          grid: {
            color: gridColor,
            drawBorder: false
          },
          ticks: {
            color: textColor,
            font: {
              family: "'JetBrains Mono', monospace",
              size: 10
            },
            maxRotation: 0
          }
        },
        y: {
          beginAtZero: false,
          grace: "10%",
          grid: {
            color: gridColor,
            drawBorder: false
          },
          ticks: {
            color: textColor,
            font: {
              family: "'JetBrains Mono', monospace",
              size: 10
            },
            callback: function(value) {
              return (value * 100).toFixed(0) + "%";
            }
          }
        }
      }
    }
  });
}

function renderDistributionChart(predictionDistribution) {
  // Destroy existing chart if any
  if (distributionChartInstance) {
    distributionChartInstance.destroy();
    distributionChartInstance = null;
  }
  
  if (!distributionChartCanvas || !predictionDistribution) return;
  
  // Collect all unique options across all models
  const allOptions = new Set();
  const models = Object.keys(predictionDistribution);
  
  models.forEach(model => {
    const modelData = predictionDistribution[model];
    Object.keys(modelData.options || {}).forEach(opt => allOptions.add(opt));
  });
  
  if (allOptions.size === 0) return;
  
  // Sort options alphabetically
  const optionLabels = Array.from(allOptions).sort();
  
  // Create shorter labels for display
  const shortLabels = optionLabels.map(opt => {
    // Extract just the outcome part (after last underscore)
    const parts = opt.split("_");
    if (parts.length >= 2) {
      const outcome = parts[parts.length - 1];
      const slug = parts.slice(0, -1).join("_");
      // Shorten slug if needed
      const shortSlug = slug.length > 15 ? slug.substring(0, 12) + "..." : slug;
      return `${shortSlug}_${outcome}`;
    }
    return opt.length > 20 ? opt.substring(0, 17) + "..." : opt;
  });
  
  // Build datasets for each model
  const datasets = models.map(model => {
    const modelData = predictionDistribution[model];
    const total = modelData.total || 1;
    const options = modelData.options || {};
    
    // Calculate percentage for each option
    const data = optionLabels.map(opt => {
      const count = options[opt] || 0;
      return (count / total) * 100; // Convert to percentage
    });
    
    const color = MODEL_COLORS[model] || CHART_COLORS[models.indexOf(model) % CHART_COLORS.length];
    
    return {
      label: model,
      data: data,
      backgroundColor: color,
      borderColor: color,
      borderWidth: 1,
      borderRadius: 4
    };
  });
  
  // Get CSS variables for theming
  const styles = getComputedStyle(document.documentElement);
  const textColor = styles.getPropertyValue("--text-secondary").trim() || "#8ba3b8";
  const gridColor = styles.getPropertyValue("--border-subtle").trim() || "rgba(0, 212, 255, 0.08)";
  
  distributionChartInstance = new Chart(distributionChartCanvas, {
    type: "bar",
    data: {
      labels: shortLabels,
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y", // Horizontal bars
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: {
            color: textColor,
            font: {
              family: "'JetBrains Mono', monospace",
              size: 10
            },
            boxWidth: 10,
            padding: 8
          }
        },
        tooltip: {
          backgroundColor: "rgba(13, 18, 32, 0.95)",
          titleColor: "#e8f4f8",
          bodyColor: "#8ba3b8",
          borderColor: "rgba(0, 212, 255, 0.3)",
          borderWidth: 1,
          padding: 10,
          titleFont: {
            family: "'JetBrains Mono', monospace",
            size: 10
          },
          bodyFont: {
            family: "'Inter', sans-serif",
            size: 11
          },
          callbacks: {
            title: function(context) {
              // Show full option name
              const index = context[0].dataIndex;
              return optionLabels[index];
            },
            label: function(context) {
              const model = context.dataset.label;
              const modelData = predictionDistribution[model];
              const optionKey = optionLabels[context.dataIndex];
              const count = (modelData.options || {})[optionKey] || 0;
              const total = modelData.total || 0;
              return `${model}: ${context.parsed.x.toFixed(1)}% (${count}/${total})`;
            }
          }
        }
      },
      scales: {
        x: {
          beginAtZero: true,
          max: 100,
          grid: {
            color: gridColor,
            drawBorder: false
          },
          ticks: {
            color: textColor,
            font: {
              family: "'JetBrains Mono', monospace",
              size: 9
            },
            callback: function(value) {
              return value + "%";
            }
          }
        },
        y: {
          grid: {
            display: false
          },
          ticks: {
            color: textColor,
            font: {
              family: "'JetBrains Mono', monospace",
              size: 9
            }
          }
        }
      }
    }
  });
}

if (backButton) {
  backButton.addEventListener("click", () => {
    window.location.href = "predictions.html";
  });
}

fetchDetails();
