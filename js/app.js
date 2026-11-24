
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
  const CHECK_TIMEOUT = 7000;

  function normalizeUrl(url) {
    if (Array.isArray(url)) url = url[0];
    if (typeof url !== "string") return "";

    return url
      .toLowerCase()
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
    const currentTab = (Tabs?.getCurrentTab?.() || "all").toLowerCase();

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
    const { start, end } = Pagination.update(filtered.length);
    const pageItems = filtered.slice(start, end);

    grid.innerHTML = "";
    pageItems.forEach(site => grid.appendChild(card(site)));

    const online = filtered.filter(site =>
      statusMap[normalizeUrl(site.url)] === "online"
    ).length;

    const offline = filtered.filter(site =>
      statusMap[normalizeUrl(site.url)] === "offline"
    ).length;

    const unverified = filtered.length - online - offline;

    stats.textContent =
      `${filtered.length} shown — ${online} online | ` +
      `${offline} unreachable | ${unverified} unverified | ${sites.length} total`;
  }

  async function loadSites() {
    try {
      const res = await fetch(`${API}/sites`);

      if (!res.ok) {
        throw new Error(`Sites API error: ${res.status}`);
      }

      const data = await res.json();
      sites = Array.isArray(data.results) ? data.results : [];

      // Begin met een neutrale status
      sites.forEach(site => {
        const key = normalizeUrl(site.url);
        if (!(key in statusMap)) {
          statusMap[key] = "unverified";
        }
      });

    } catch (error) {
      console.error("Could not load sites:", error);
      stats.textContent = "API not reachable";
      sites = [];
    }

    Pagination.reset();
    render();
  }

  // Controleer één website vanuit de browser.
  // Een CORS-blokkade betekent unverified, niet offline.
  async function checkSite(site) {
    const originalUrl = getUrl(site.url);
    if (!originalUrl) return "unverified";

    let url = originalUrl;

    if (!/^https?:\/\//i.test(url)) {
      url = "https://" + url;
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), CHECK_TIMEOUT);

    try {
      await fetch(url, {
        method: "HEAD",
        mode: "no-cors",
        cache: "no-store",
        signal: controller.signal
      });

      // no-cors geeft een opaque response. We kunnen de HTTP-status
      // niet betrouwbaar lezen, dus dit is geen bewezen online-status.
      return "unverified";

    } catch (error) {
      if (error.name === "AbortError") {
        return "unverified";
      }

      return "unverified";

    } finally {
      clearTimeout(timeout);
    }
  }

  async function recheckAll() {
    if (isChecking || sites.length === 0) return;

    isChecking = true;

    if (recheckBtn) {
      recheckBtn.disabled = true;
    }

    const total = sites.length;
    let completed = 0;

    // Toon eerst dat de controles opnieuw gestart zijn
    sites.forEach(site => {
      statusMap[normalizeUrl(site.url)] = "unverified";
    });

    render();

    try {
      for (let i = 0; i < total; i += BATCH_SIZE) {
        const batch = sites.slice(i, i + BATCH_SIZE);

        await Promise.all(
          batch.map(async site => {
            const key = normalizeUrl(site.url);
            statusMap[key] = await checkSite(site);
            completed++;
          })
        );

        if (recheckBtn) {
          recheckBtn.textContent = `checking ${completed}/${total}`;
        }

        render();
      }
    } finally {
      isChecking = false;

      if (recheckBtn) {
        recheckBtn.disabled = false;
        recheckBtn.textContent = "recheck all";
      }

      render();
    }
  }

  search?.addEventListener("input", () => {
    Pagination.reset();
    render();
  });

  recheckBtn?.addEventListener("click", recheckAll);

  Tabs?.init?.(() => {
    Pagination.reset();
    render();
  });

  Pagination?.init?.((page, isNext) => {
    if (isNext) {
      Pagination.goToPage(Pagination.getCurrentPage() + 1);
    } else {
      Pagination.goToPage(page);
    }

    render();
  });

  loadSites();
});
