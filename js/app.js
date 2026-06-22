document.addEventListener("DOMContentLoaded", () => {
  const API = "http://127.0.0.1:5000";

  const grid = document.getElementById("grid");
  const search = document.getElementById("search");
  const recheckBtn = document.getElementById("recheck");
  const stats = document.getElementById("stats");

  let sites = [];
  let statusMap = {};

  // ----------------------------
  // URL NORMALIZATION (FIXED FOR ARRAYS + ANIMIO BUG)
  // ----------------------------
  function normalizeUrl(url) {
    if (!url) return "";

    if (Array.isArray(url)) {
      url = url[0];
    }

    if (typeof url !== "string") return "";

    return url
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split("#")[0]
      .replace(/\/$/, "")
      .trim();
  }

  // ----------------------------
  // CATEGORY HANDLING (FIXED)
  // ----------------------------
  function getCategories(site) {
    const c = site?.category;

    if (!c) return [];

    if (Array.isArray(c)) {
      return c.map(x => String(x).toLowerCase().trim());
    }

    if (typeof c === "string") {
      return c.split(",").map(x => x.toLowerCase().trim()).filter(Boolean);
    }

    return [];
  }

  function statusClass(s) {
    if (s === "online") return "online";
    if (s === "offline" || s === "down" || s === "unreachable") return "down";
    return "unknown";
  }

  function statusLabel(s) {
    if (!s || s === "unchecked") return "unchecked";
    if (s === "unverified") return "unverified";
    return s;
  }

  // ----------------------------
  // FILTER (FIXED MULTI CATEGORY MATCH)
  // ----------------------------
  function getFiltered() {
    const q = (search?.value || "").toLowerCase();
    const currentTab = (Tabs?.getCurrentTab?.() || "all").toLowerCase();

    return sites.filter(s => {
      const nameMatch = (s.name || "").toLowerCase().includes(q);

      const cats = getCategories(s);

      const tabMatch =
        currentTab === "all" ||
        cats.includes(currentTab); // IMPORTANT FIX: multi-category works

      return nameMatch && tabMatch;
    });
  }

  // ----------------------------
  // CARD
  // ----------------------------
  function card(site) {
    const key = normalizeUrl(site.url);
    const status = statusMap[key] || "unchecked";

    const el = document.createElement("div");
    el.className = "card";

    el.innerHTML = `
      <div class="card-top">
        <a class="name" href="${Array.isArray(site.url) ? site.url[0] : site.url}" target="_blank">
          ${site.name}
        </a>
      </div>

      <div class="url">${Array.isArray(site.url) ? site.url[0] : site.url}</div>

      <div class="card-tags">
        ${getCategories(site).map(c => `<span class="card-tag">${c}</span>`).join("")}
      </div>

      <div class="status-row">
        <span class="ping ${statusClass(status)}"></span>
        <span class="status-text ${statusClass(status)}">${statusLabel(status)}</span>
      </div>
    `;

    return el;
  }

  // ----------------------------
  // RENDER
  // ----------------------------
  function render() {
    const filtered = getFiltered();

    const { start, end } = Pagination.update(filtered.length);
    const pageItems = filtered.slice(start, end);

    grid.innerHTML = "";
    pageItems.forEach(s => grid.appendChild(card(s)));

    const online = filtered.filter(s => {
      const key = normalizeUrl(s.url);
      return statusMap[key] === "online";
    }).length;

    stats.innerHTML = `
      <b>${filtered.length}</b> shown —
      <b>${online}</b> online &nbsp;|&nbsp;
      <b>${sites.length}</b> total
    `;
  }

  // ----------------------------
  // LOAD SITES (FIXED)
  // ----------------------------
  async function loadSites() {
    try {
      const res = await fetch(`${API}/sites`);
      const data = await res.json();

      sites = Array.isArray(data.results) ? data.results : [];

    } catch (e) {
      console.error(e);
      stats.textContent = "API not reachable";
      sites = [];
    }

    Pagination.reset();
    render();
  }

  // ----------------------------
  // LOAD STATUS (FIXED + MAPPING FIX)
  // ----------------------------
  async function loadStatus() {
    try {
      const res = await fetch(`${API}/status`);
      const data = await res.json();

      console.log("STATUS RESPONSE:", data); // 👈 HERE

      statusMap = {};

      if (Array.isArray(data.results)) {
        data.results.forEach(s => {
          const key = normalizeUrl(s.url);
          statusMap[key] = s.status;
        });
      }

    } catch (e) {
      console.error(e);
      statusMap = {};
    }

    render();
  }

  // ----------------------------
  // EVENTS
  // ----------------------------
  search?.addEventListener("input", () => {
    Pagination.reset();
    render();
  });

  recheckBtn?.addEventListener("click", async () => {
    recheckBtn.disabled = true;
    recheckBtn.textContent = "checking...";
    await loadStatus();
    recheckBtn.disabled = false;
    recheckBtn.textContent = "recheck all";
  });

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

  // ----------------------------
  // INIT
  // ----------------------------
  loadSites();
  loadStatus();
  setInterval(loadStatus, 5000);
});