/**
 * FutureShow - Agent Forecast Dashboard
 * Digital theme with card-based layout
 */

const API_BASE = location.origin.replace(/\/$/, "");

// DOM Elements
const cardsGrid = document.getElementById("cardsGrid");
const searchBox = document.getElementById("searchBox");
const loadingOverlay = document.getElementById("loadingOverlay");
const emptyState = document.getElementById("emptyState");
const activeCountEl = document.getElementById("activeCount");
const closedCountEl = document.getElementById("closedCount");
const lastUpdatedEl = document.getElementById("lastUpdated");
const modelCountEl = document.getElementById("modelCount");
const forecastSection = document.getElementById("forecastSection");
const leaderboardSection = document.getElementById("leaderboardSection");
const leaderboardList = document.getElementById("leaderboardList");
const leaderboardEmpty = document.getElementById("leaderboardEmpty");
const navForecasts = document.getElementById("navForecasts");
const navLeaderboard = document.getElementById("navLeaderboard");

// State
let cache = [];
let modelSummary = {};
let humanSummary = {};
let currentTab = "active";
let initialLoad = true;

// Model configurations with icons
const MODEL_CONFIG = {
  "gemini-2.5-pro": {
    name: "Gemini",
    shortName: "Gem",
    icon: "icons/gemini-2.5-pro.svg",
    color: "#4285f4"
  },
  "gemini-3-flash": {
    name: "Gemini Flash",
    shortName: "Gem",
    icon: "icons/gemini-2.5-pro.svg",
    color: "#4285f4"
  },
  "gemini-3-flash-preview": {
    name: "Gemini Flash",
    shortName: "Gem",
    icon: "icons/gemini-2.5-pro.svg",
    color: "#4285f4"
  },
  "claude-4.5-sonnet": {
    name: "Claude",
    shortName: "Cla",
    icon: "icons/claude-4.5-sonnet.svg",
    color: "#d97757"
  },
  "gpt-5": {
    name: "GPT-5",
    shortName: "GPT",
    icon: "icons/gpt-5.svg",
    color: "#10a37f"
  },
  "deepseek-v3.1": {
    name: "DeepSeek",
    shortName: "DS",
    icon: "icons/deepseek-v3.1.svg",
    color: "#7c3aed"
  }
};

// Max options to show before truncating
const MAX_OPTIONS_DISPLAY = 5;

/**
 * Set loading state
 */
function setLoading(show) {
  if (!loadingOverlay) return;
  loadingOverlay.classList.toggle("hidden", !show);
}

/**
 * Format date for display
 */
function formatDate(dateStr) {
  if (!dateStr) return "--";
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

/**
 * Get model configuration
 */
function getModelConfig(modelName) {
  return MODEL_CONFIG[modelName] || {
    name: modelName,
    shortName: modelName.substring(0, 3),
    icon: null,
    color: "#6b7280"
  };
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Normalize string for comparison (remove special chars, lowercase)
 */
function normalizeForComparison(str) {
  if (!str) return "";
  return str.toLowerCase()
    .replace(/[^a-z0-9]/g, "") // Remove all non-alphanumeric
    .trim();
}

/**
 * Fetch data from API
 */
async function fetchData() {
  try {
    if (initialLoad) setLoading(true);

    const resp = await fetch(`${API_BASE}/api/predictions`);
    const data = await resp.json();

    if (!data.ok) throw new Error(data.error || "Failed to load data");

    cache = data.events || [];
    modelSummary = data.model_summary || {};
    humanSummary = data.human_summary || {};

    // Update UI
    updateCounts();
    updateLastUpdated();
    updateModelCount();
    render();
    updateLeaderboard();

  } catch (err) {
    console.error("Failed to fetch predictions:", err);
    if (!cache.length) {
      showEmpty("Failed to load data. Please try again.");
    }
  } finally {
    if (initialLoad) {
      setLoading(false);
      initialLoad = false;
    }
  }
}

/**
 * Update tab counts
 */
function updateCounts() {
  const activeEvents = cache.filter(ev => !ev.result);
  const closedEvents = cache.filter(ev => ev.result);
  
  if (activeCountEl) activeCountEl.textContent = activeEvents.length;
  if (closedCountEl) closedCountEl.textContent = closedEvents.length;
}

/**
 * Update last updated timestamp
 */
function updateLastUpdated() {
  if (lastUpdatedEl) {
    lastUpdatedEl.textContent = new Date().toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit"
    });
  }
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

function updateLeaderboard() {
  if (!leaderboardList || !leaderboardEmpty) return;
  leaderboardList.innerHTML = "";

  const entries = buildLeaderboardEntries();
  if (!entries.length) {
    leaderboardEmpty.classList.remove("hidden");
    return;
  }
  leaderboardEmpty.classList.add("hidden");
  const frag = document.createDocumentFragment();
  entries.forEach((entry, idx) => {
    const row = document.createElement("div");
    row.className = "leaderboard-row";

    const rank = document.createElement("div");
    rank.className = "leaderboard-rank";
    rank.textContent = `${idx + 1}`;

    const modelCell = document.createElement("div");
    modelCell.className = "leaderboard-model";
    const avatar = renderModelAvatar({ model: entry.model }, "normal");
    avatar.classList.add("leaderboard-avatar");
    const name = document.createElement("div");
    name.className = "leaderboard-name";
    name.textContent = getModelConfig(entry.model).name;
    modelCell.append(avatar, name);

    const correct = document.createElement("div");
    correct.className = "leaderboard-correct";
    correct.textContent = `${entry.correct}/${entry.total}`;

    const acc = document.createElement("div");
    acc.className = "leaderboard-acc";
    acc.textContent = `${entry.pct.toFixed(1)}%`;

    // Human Accuracy column
    const humanAccCell = document.createElement("div");
    humanAccCell.className = "leaderboard-human-acc";
    if (entry.humanAccuracy !== null) {
      humanAccCell.textContent = `${entry.humanAccuracy.toFixed(1)}%`;
      humanAccCell.title = "Market consensus accuracy on the same prediction points";
    } else {
      humanAccCell.textContent = "--";
      humanAccCell.title = "No human baseline data available";
    }

    // vs Human column
    const vsMarketCell = document.createElement("div");
    vsMarketCell.className = "leaderboard-vs-market";
    if (entry.vsMarket !== null) {
      const vsNum = entry.vsMarket >= 0 ? `+${entry.vsMarket.toFixed(1)}%` : `${entry.vsMarket.toFixed(1)}%`;
      const vsClass = entry.vsMarket >= 0 ? "positive" : "negative";
      vsMarketCell.innerHTML = `<span class="${vsClass}">${vsNum}</span>`;
      vsMarketCell.title = "Model accuracy minus human accuracy on same predictions";
    } else {
      vsMarketCell.textContent = "--";
      vsMarketCell.title = "No human baseline data available";
    }

    // Prediction Value column
    const predValueCell = document.createElement("div");
    predValueCell.className = "leaderboard-pred-value";
    if (entry.predValue !== null) {
      const valueNum = entry.predValue.toFixed(3);
      const valueClass = entry.predValue >= 0 ? "positive" : "negative";
      predValueCell.innerHTML = `<span class="${valueClass}">${valueNum}</span>`;
      predValueCell.title = `Prediction Value based on ${entry.valueCount} predictions with market probability data`;
    } else {
      predValueCell.textContent = "--";
      predValueCell.title = "No market probability data available";
    }

    row.append(rank, modelCell, correct, acc, humanAccCell, vsMarketCell, predValueCell);
    frag.appendChild(row);
  });
  leaderboardList.appendChild(frag);
}


function buildLeaderboardEntries() {
  const entries = [];

  // humanSummary is now per-model: {model: {correct, total}, ...}
  Object.entries(modelSummary || {}).forEach(([model, stat]) => {
    if (!stat || typeof stat !== "object" || !stat.total) return;
    const pct = ((stat.correct / stat.total) * 100);

    // Calculate prediction value (average of value_sum)
    const valueSum = stat.value_sum || 0;
    const valueCount = stat.value_count || 0;
    const predValue = valueCount > 0 ? (valueSum / valueCount) : null;

    // Get human (market) accuracy for THIS model
    const humanStat = humanSummary[model] || {};
    const humanTotal = humanStat.total || 0;
    const humanCorrect = humanStat.correct || 0;
    const humanAccuracy = humanTotal > 0 ? (humanCorrect / humanTotal) * 100 : null;

    // Calculate vs Market (model accuracy - human accuracy for same predictions)
    const vsMarket = humanAccuracy !== null ? (pct - humanAccuracy) : null;

    entries.push({
      model,
      correct: stat.correct || 0,
      total: stat.total || 0,
      pct,
      predValue,
      valueCount,
      vsMarket,
      humanAccuracy  // Store for display if needed
    });
  });
  // Sort by prediction value (descending), then by accuracy, then by total
  entries.sort((a, b) => {
    // If both have prediction values, sort by that first
    if (a.predValue !== null && b.predValue !== null) {
      if (b.predValue !== a.predValue) return b.predValue - a.predValue;
    } else if (a.predValue !== null) {
      return -1; // a has value, b doesn't
    } else if (b.predValue !== null) {
      return 1; // b has value, a doesn't
    }
    // Fallback to accuracy
    if (b.pct !== a.pct) return b.pct - a.pct;
    if (b.total !== a.total) return b.total - a.total;
    return a.model.localeCompare(b.model);
  });
  return entries;
}

function setView(view) {
  const showLeaderboard = view === "leaderboard";
  if (forecastSection) forecastSection.classList.toggle("hidden", showLeaderboard);
  if (leaderboardSection) leaderboardSection.classList.toggle("hidden", !showLeaderboard);
  if (navForecasts) navForecasts.classList.toggle("active", !showLeaderboard);
  if (navLeaderboard) navLeaderboard.classList.toggle("active", showLeaderboard);
}

/**
 * Update model count in footer
 */
function updateModelCount() {
  const models = new Set();
  cache.forEach(ev => {
    (ev.predictions || []).forEach(p => {
      if (p.model) models.add(p.model);
    });
  });
  if (modelCountEl) {
    modelCountEl.textContent = `${models.size} models active`;
  }
}

/**
 * Show empty state
 */
function showEmpty(message) {
  if (cardsGrid) cardsGrid.innerHTML = "";
  if (emptyState) {
    emptyState.classList.remove("hidden");
    const textEl = emptyState.querySelector(".empty-text");
    if (textEl && message) textEl.textContent = message;
  }
}

/**
 * Hide empty state
 */
function hideEmpty() {
  if (emptyState) emptyState.classList.add("hidden");
}

/**
 * Process predictions into option groups using backend-provided options and gt_id.
 * 
 * Data from backend:
 * - event.options: [{id, show_name, market_slug, outcome}, ...]
 * - event.gt_id: the winning option ID (e.g., "slug_Yes" or "slug_No")
 * - prediction.option_id: the option ID this model selected (e.g., "slug_Yes")
 */
function processOptionsFromPredictions(predictions, event) {
  const abstainOptionId = "__ABSTAIN__";
  
  // Get options and gt_id from event
  const options = event.options || [];
  const gtId = event.gt_id;
  
  // Build option map from backend-provided options
  // Key: option_id, Value: { id, name, models: [], isWinner: bool }
  const optionMap = new Map();
  
  options.forEach(opt => {
    const optId = opt.id;
    if (!optId) return;
    optionMap.set(optId, {
      id: optId,
      name: opt.show_name || optId,  // show_name is same as id now
      models: [],
      isWinner: gtId ? (optId === gtId) : false
    });
  });
  
  // Get winning option name for display
  let winningOptionName = null;
  if (gtId) {
    const winnerOpt = optionMap.get(gtId);
    if (winnerOpt) {
      winningOptionName = winnerOpt.name;
    } else {
      // GT not in options, use gtId as name
      winningOptionName = gtId;
    }
  }
  
  // Process each prediction
  predictions.forEach(pred => {
    const model = pred.model;
    const call = (pred.call || "").toUpperCase();
    let optionId = pred.option_id;
    
    if (call === "ABSTAIN") {
      optionId = abstainOptionId;
    } else if (!optionId) {
      return;
    }

    // Find or create the option entry
    if (!optionMap.has(optionId)) {
      // Option not in the predefined list - create a fallback entry
      optionMap.set(optionId, {
        id: optionId,
        name: optionId === abstainOptionId ? "ABSTAIN" : optionId,
        models: [],
        isWinner: gtId ? (optionId === gtId) : false
      });
    }
    
    // Check if prediction is correct
    const isCorrect = gtId ? (optionId === gtId) : pred.success;
    
    // Add model to this option
    optionMap.get(optionId).models.push({
      model,
      call,
      success: isCorrect,
      timestamp: pred.timestamp
    });
  });
  
  // Convert to array and sort by model count (descending)
  const sortedOptions = Array.from(optionMap.values())
    .filter(opt => opt.models.length > 0 || opt.isWinner) // Only keep options with models or the winner
    .sort((a, b) => b.models.length - a.models.length);
  
  return { options: sortedOptions, winningOptionName };
}


/**
 * Render model avatar
 */
function renderModelAvatar(modelInfo, size = "normal") {
  const config = getModelConfig(modelInfo.model);
  const sizeClass = size === "small" ? "abstain-avatar" : "model-avatar";
  const successClass = modelInfo.success === true ? "success" : 
                       modelInfo.success === false ? "failed" : "";
  
  const avatar = document.createElement("div");
  avatar.className = `${sizeClass} ${successClass}`.trim();
  avatar.setAttribute("data-tooltip", config.name);
  
  if (config.icon) {
    const img = document.createElement("img");
    img.src = config.icon;
    img.alt = config.name;
    img.onerror = () => {
      // Fallback to text if image fails
      avatar.innerHTML = `<span style="font-size: 10px; font-weight: 600;">${config.shortName}</span>`;
    };
    avatar.appendChild(img);
  } else {
    avatar.innerHTML = `<span style="font-size: 10px; font-weight: 600;">${config.shortName}</span>`;
  }
  
  return avatar;
}

/**
 * Render a single event card
 */
function renderCard(event) {
  const card = document.createElement("div");
  const isClosed = !!event.result;
  card.className = `event-card ${isClosed ? "event-closed" : "event-active"}`;
  card.addEventListener("click", () => openDetails(event.slug));
  const { options, winningOptionName } = processOptionsFromPredictions(
    event.predictions || [], 
    event
  );
  
  // Card Header
  const header = document.createElement("div");
  header.className = "card-header";
  
  const title = document.createElement("div");
  title.className = "card-title";
  title.textContent = event.title || event.slug;
  
  const meta = document.createElement("div");
  meta.className = "card-meta";
  
  // Probability badge
  if (event.market_probability !== null && event.market_probability !== undefined) {
    const prob = document.createElement("div");
    prob.className = "card-prob";
    prob.textContent = `${Math.round(event.market_probability * 100)}%`;
    meta.appendChild(prob);
  }
  
  // Status indicator
  const status = document.createElement("div");
  status.className = "card-status";
  const statusDot = document.createElement("span");
  statusDot.className = `status-indicator ${isClosed ? "closed" : ""}`;
  const statusText = document.createElement("span");
  statusText.textContent = isClosed ? "Resolved" : "Active";
  status.append(statusDot, statusText);
  meta.appendChild(status);

  // Per-model accuracy display
  const modelStats = event.model_stats || {};
  if (Object.keys(modelStats).length > 0) {
    const accContainer = document.createElement("div");
    accContainer.className = "card-acc-container";
    
    // Add "Acc" label
    const accLabel = document.createElement("span");
    accLabel.className = "card-acc-label";
    accLabel.textContent = "Acc";
    accContainer.appendChild(accLabel);
    
    Object.entries(modelStats).forEach(([modelName, stat]) => {
      if (!stat || !stat.total) return;
      const pct = Math.round((stat.correct / stat.total) * 100);
      const config = getModelConfig(modelName);
      
      const accItem = document.createElement("div");
      accItem.className = "card-acc-item";
      accItem.setAttribute("data-tooltip", `${config.name}: ${stat.correct}/${stat.total}`);
      
      // Model icon
      if (config.icon) {
        const icon = document.createElement("img");
        icon.src = config.icon;
        icon.alt = config.shortName;
        icon.className = "card-acc-icon";
        accItem.appendChild(icon);
      } else {
        const iconText = document.createElement("span");
        iconText.className = "card-acc-icon-text";
        iconText.textContent = config.shortName;
        accItem.appendChild(iconText);
      }
      
      // Accuracy percentage
      const accPct = document.createElement("span");
      accPct.className = "card-acc-pct";
      accPct.textContent = `${pct}%`;
      accItem.appendChild(accPct);
      
      accContainer.appendChild(accItem);
    });
    
    meta.appendChild(accContainer);
  }
  
  header.append(title, meta);
  
  // Ground Truth Banner (for closed events)
  if (isClosed && winningOptionName) {
    const truthBanner = document.createElement("div");
    truthBanner.className = "ground-truth-banner";
    truthBanner.innerHTML = `
      <span class="truth-icon">✓</span>
      <span class="truth-label">ANSWER:</span>
      <span class="truth-value">${escapeHtml(winningOptionName)}</span>
    `;
    header.appendChild(truthBanner);
  }
  
  // Card Body - Options List
  const body = document.createElement("div");
  body.className = "card-body";
  
  const optionsList = document.createElement("div");
  optionsList.className = "options-list";
  
  // Render options (limited)
  const displayOptions = options.slice(0, MAX_OPTIONS_DISPLAY);
  const hiddenCount = options.length - displayOptions.length;
  
  displayOptions.forEach((opt, index) => {
    const item = document.createElement("div");
    item.className = `option-item ${opt.isWinner ? "winner" : ""}`;
    
    // Left side: rank + name
    const left = document.createElement("div");
    left.className = "option-left";
    
    const rank = document.createElement("div");
    rank.className = "option-rank";
    rank.textContent = `${index + 1}`;
    
    const name = document.createElement("div");
    name.className = "option-name";
    name.textContent = opt.name;
    name.title = opt.name;
    
    left.append(rank, name);
    
    // Right side: model avatars + count
    const right = document.createElement("div");
    right.className = "option-right";
    
    // Model avatars (max 4)
    const avatars = document.createElement("div");
    avatars.className = "model-avatars";
    
    const displayModels = opt.models.slice(0, 4);
    displayModels.forEach(m => {
      avatars.appendChild(renderModelAvatar(m));
    });
    
    if (opt.models.length > 4) {
      const more = document.createElement("div");
      more.className = "model-avatar";
      more.innerHTML = `<span style="font-size: 10px;">+${opt.models.length - 4}</span>`;
      avatars.appendChild(more);
    }
    
    // Vote count
    const count = document.createElement("div");
    count.className = "vote-count";
    count.textContent = opt.models.length;
    
    right.append(avatars, count);
    item.append(left, right);
    optionsList.appendChild(item);
  });
  
  // Show "more options" indicator
  if (hiddenCount > 0) {
    const more = document.createElement("div");
    more.className = "options-more";
    more.textContent = `+ ${hiddenCount} more option${hiddenCount > 1 ? "s" : ""}`;
    optionsList.appendChild(more);
  }
  
  // Handle case with no options
  if (options.length === 0) {
    const empty = document.createElement("div");
    empty.className = "options-more";
    empty.textContent = "No predictions yet";
    optionsList.appendChild(empty);
  }
  
  body.appendChild(optionsList);
  
  // Assemble card
  card.append(header, body);
  
  return card;
}

/**
 * Main render function
 */
function render() {
  const searchTerm = (searchBox?.value || "").toLowerCase().trim();
  
  // Filter events
  let filtered = cache.filter(ev => {
    // Tab filter
    const isClosed = !!ev.result;
    if (currentTab === "active" && isClosed) return false;
    if (currentTab === "closed" && !isClosed) return false;
    
    // Search filter
    if (searchTerm) {
      const text = `${ev.title || ""} ${ev.slug || ""} ${ev.description || ""}`.toLowerCase();
      if (!text.includes(searchTerm)) return false;
    }
    
    return true;
  });
  
  // Check if empty
  if (!filtered.length) {
    showEmpty(`No ${currentTab} events found`);
    return;
  }
  
  hideEmpty();
  
  // Render cards
  const fragment = document.createDocumentFragment();
  filtered.forEach(event => {
    fragment.appendChild(renderCard(event));
  });
  
  cardsGrid.innerHTML = "";
  cardsGrid.appendChild(fragment);
}

/**
 * Open event details page
 */
function openDetails(slug) {
  if (!slug) return;
  window.location.href = `details.html?slug=${encodeURIComponent(slug)}`;
}

/**
 * Handle tab switching
 */
function handleTabClick(event) {
  const tab = event.target.closest(".tab");
  if (!tab) return;
  
  const tabName = tab.dataset.tab;
  if (tabName === currentTab) return;
  
  // Update active state
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  tab.classList.add("active");
  
  currentTab = tabName;
  render();
}

// Event Listeners
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", handleTabClick);
});

if (navForecasts) {
  navForecasts.addEventListener("click", (event) => {
    event.preventDefault();
    setView("forecasts");
    // Update URL without page reload
    history.pushState({}, "", "predictions.html");
  });
}

if (navLeaderboard) {
  navLeaderboard.addEventListener("click", (event) => {
    event.preventDefault();
    setView("leaderboard");
    updateLeaderboard();
    // Update URL without page reload
    history.pushState({}, "", "predictions.html?view=leaderboard");
  });
}

if (searchBox) {
  searchBox.addEventListener("input", () => {
    render();
  });
}

// Initial load - check URL params for view
const urlParams = new URLSearchParams(window.location.search);
const initialView = urlParams.get("view") === "leaderboard" ? "leaderboard" : "forecasts";
setView(initialView);
fetchData();

// Auto-refresh every 30 seconds
setInterval(fetchData, 30000);
