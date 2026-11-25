
document.addEventListener("DOMContentLoaded", () => {
  const API = window.ANIME_API_BASE || "https://animelist-tusl.onrender.com";

  const grid = document.getElementById("grid");
  const search = document.getElementById("search");
  const recheckBtn = document.getElementById("recheck");
  const stats = document.getElementById("stats");

  let sites = [];
  let statusMap = {};
  let isChecking = false;

  const BATCH_SIZE = 10;

  // Automatic checking: once when the page opens, then again 60s after each
  // run finishes (so a slow run can never overlap the next one).
  const AUTO_RECHECK_MS = 60 * 1000;
  let autoTimer = null;
  let lastCheckedAt = null;

  function normalizeUrl(url) {
    if (Array.isArray(url)) url = url[0];
    if (typeof url !== "string") return "";

    return url.toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split("#")[0]
      .replace(/\/$/, "")
      .trim();
  }

  function getUrl(url) {
    if (Array.isArray(url)) return url[0] || "";
    return typeof url === "string" ? url : "";
  }

  function getCategories(site) {
    const c = site?.category;
    if (!c) return [];

    const categories = Array.isArray(c) ? c : String(c).split(",");

    return categories
      .map(x => String(x).toLowerCase().trim())
      .filter(Boolean);
  }

  function statusClass(status) {
    if (status === "online") return "online";
    if (status === "offline") return "down";
    return "unknown";
  }

  function statusLabel(status) {
    if (status === "online") return "reachable";
    if (status === "offline") return "unreachable";
    return "unverified";
  }

  function getFiltered() {
    const q = (search?.value || "").toLowerCase();

    const currentTab =
      typeof Tabs !== "undefined"
        ? (Tabs.getCurrentTab?.() || "all").toLowerCase()
        : "all";

    return sites.filter(site => {
      const nameMatch = (site.name || "").toLowerCase().includes(q);
      const tabMatch =
        currentTab === "all" ||
        getCategories(site).includes(currentTab);

      return nameMatch && tabMatch;
    });
  }

  function card(site) {
    const key = normalizeUrl(site.url);
    const status = statusMap[key] || "unverified";
    const url = getUrl(site.url);

    const el = document.createElement("div");
    el.className = "card";

    const top = document.createElement("div");
    top.className = "card-top";

    const link = document.createElement("a");
    link.className = "name";
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = site.name || "Unknown";

    top.appendChild(link);

    const urlEl = document.createElement("div");
    urlEl.className = "url";
    urlEl.textContent = url;

    const tags = document.createElement("div");
    tags.className = "card-tags";

    getCategories(site).forEach(category => {
      const tag = document.createElement("span");
      tag.className = "card-tag";
      tag.textContent = category;
      tags.appendChild(tag);
    });

    const statusRow = document.createElement("div");
    statusRow.className = "status-row";

    const ping = document.createElement("span");
    ping.className = `ping ${statusClass(status)}`;

    const label = document.createElement("span");
    label.className = `status-text ${statusClass(status)}`;
    label.textContent = statusLabel(status);

    statusRow.append(ping, label);
    el.append(top, urlEl, tags, statusRow);

    return el;
  }

  function render() {
    if (!grid || !stats) return;

    const filtered = getFiltered();

    let start = 0;
    let end = filtered.length;

    if (typeof Pagination !== "undefined") {
      const page = Pagination.update(filtered.length);
      start = page.start;
      end = page.end;
    }

    grid.innerHTML = "";

    filtered.slice(start, end).forEach(site => {
      grid.appendChild(card(site));
    });

    const online = filtered.filter(site =>
      statusMap[normalizeUrl(site.url)] === "online"
    ).length;

    const offline = filtered.filter(site =>
      statusMap[normalizeUrl(site.url)] === "offline"
    ).length;

    const unverified = filtered.length - online - offline;

    let checkedText = "";
    if (lastCheckedAt) {
      checkedText =
        " · checked " + new Date(lastCheckedAt).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit"
        });
    }

    stats.textContent =
      `${filtered.length} shown — ` +
      `${online} online | ${offline} unreachable | ` +
      `${unverified} unverified | ${sites.length} total` +
      checkedText;
  }

  async function loadSites() {
    try {
      const response = await fetch(`${API}/sites`);

      if (!response.ok) {
        throw new Error(`Sites API error: ${response.status}`);
      }

      const data = await response.json();
      sites = Array.isArray(data.results) ? data.results : [];

      sites.forEach(site => {
        const key = normalizeUrl(site.url);
        if (!(key in statusMap)) {
          statusMap[key] = "unverified";
        }
      });

    } catch (error) {
      console.error("Could not load sites:", error);
      if (stats) stats.textContent = "API not reachable";
      sites = [];
    }

    if (typeof Pagination !== "undefined") {
      Pagination.reset();
    }

    render();
  }

  async function checkBatch(batch, startIndex) {
    const indices = batch.map((site, i) => startIndex + i);

    const response = await fetch(`${API}/check-batch`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ indices })
    });

    if (!response.ok) {
      throw new Error(`Batch check failed: HTTP ${response.status}`);
    }

    const data = await response.json();

    if (!Array.isArray(data.results)) {
      throw new Error("Invalid batch response");
    }

    data.results.forEach(result => {
      const key = normalizeUrl(result.url);

      if (key) {
        statusMap[key] = result.status;
      }
    });
  }

  async function recheckAll() {
    if (isChecking || sites.length === 0) return false;

    isChecking = true;

    if (recheckBtn) {
      recheckBtn.disabled = true;
    }

    const total = sites.length;
    let completed = 0;
    let failedBatches = 0;

    // Keep the previous results visible while a new run is in progress: each
    // batch updates its own entries as soon as its response arrives.
    render();

    try {
      for (let i = 0; i < total; i += BATCH_SIZE) {
        const batch = sites.slice(i, i + BATCH_SIZE);

        try {
          await checkBatch(batch, i);
        } catch (error) {
          failedBatches++;
          console.error("Batch error:", error);
        }

        completed += batch.length;

        if (recheckBtn) {
          recheckBtn.textContent = `checking ${completed}/${total}`;
        }

        render();
      }
    } finally {
      isChecking = false;
      lastCheckedAt = Date.now();

      if (recheckBtn) {
        recheckBtn.disabled = false;
        recheckBtn.textContent =
          failedBatches > 0 ? "recheck all (some failed)" : "recheck all";
      }

      render();

      console.log("Recheck complete:", {
        total,
        online: Object.values(statusMap).filter(s => s === "online").length,
        offline: Object.values(statusMap).filter(s => s === "offline").length,
        failedBatches
      });
    }

    return true;
  }

  function scheduleAutoCheck(delay = AUTO_RECHECK_MS) {
    clearTimeout(autoTimer);
    autoTimer = setTimeout(runAutoCheck, delay);
  }

  async function runAutoCheck() {
    // Don't burn requests while the tab is in the background; resume as soon
    // as the user comes back to the page.
    if (document.visibilityState === "hidden") {
      return;
    }

    // The API is on a free host that sleeps, so retry the list load if the
    // first attempt failed or returned nothing.
    if (sites.length === 0) {
      await loadSites();
    }

    await recheckAll();
    scheduleAutoCheck();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || isChecking) return;

    const stale =
      !lastCheckedAt || Date.now() - lastCheckedAt >= AUTO_RECHECK_MS;

    if (stale) {
      clearTimeout(autoTimer);
      runAutoCheck();
    }
  });

  search?.addEventListener("input", () => {
    if (typeof Pagination !== "undefined") {
      Pagination.reset();
    }
    render();
  });

  recheckBtn?.addEventListener("click", async () => {
    clearTimeout(autoTimer);
    await recheckAll();
    scheduleAutoCheck();
  });

  if (typeof Tabs !== "undefined") {
    Tabs.init?.(() => {
      if (typeof Pagination !== "undefined") {
        Pagination.reset();
      }
      render();
    });
  }

  if (typeof Pagination !== "undefined") {
    Pagination.init?.((page, isNext) => {
      if (isNext) {
        Pagination.goToPage(Pagination.getCurrentPage() + 1);
      } else {
        Pagination.goToPage(page);
      }
      render();
    });
  }

  // Check every link as soon as the page opens, then repeat every 60s.
  loadSites().then(() => scheduleAutoCheck(0));
});
