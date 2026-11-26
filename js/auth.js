// ---------------------------------------------------------------- access gate
//
// The directory is private: the API rejects every data request unless it
// carries a signed token. This script asks for credentials, stores the token
// in localStorage and hands out an `apiFetch` helper that app.js uses for all
// calls.
(() => {
  const API = window.ANIME_API_BASE || "https://animelist-tusl.onrender.com";
  const STORAGE_KEY = "aniquest.token";

  const screen = document.getElementById("login-screen");
  const form = document.getElementById("login-form");
  const userInput = document.getElementById("login-user");
  const passInput = document.getElementById("login-pass");
  const errorEl = document.getElementById("login-error");
  const submitBtn = document.getElementById("login-submit");
  const chip = document.getElementById("session-chip");
  const chipUser = document.getElementById("session-user");
  const logoutBtn = document.getElementById("logout-btn");

  if (!screen || !form) {
    console.error("Login markup missing from index.html");
    return;
  }

  let token = localStorage.getItem(STORAGE_KEY) || "";
  let user = "";
  let resolved = false;
  let resolveReady;

  const ready = new Promise(resolve => {
    resolveReady = resolve;
  });

  function finish() {
    if (resolved) return;
    resolved = true;
    resolveReady();
  }

  function showLogin(message) {
    screen.hidden = false;
    document.body.classList.add("locked");

    if (message) {
      errorEl.textContent = message;
    }

    setTimeout(() => userInput.focus(), 60);
  }

  function signedIn(name) {
    user = name || "user";
    screen.hidden = true;
    document.body.classList.remove("locked");

    if (chip) chip.hidden = false;
    if (chipUser) chipUser.textContent = user;
  }

  function clearToken() {
    token = "";
    user = "";
    localStorage.removeItem(STORAGE_KEY);

    if (chip) chip.hidden = true;
  }

  async function sessionUser() {
    if (!token) return null;

    try {
      const response = await fetch(`${API}/session`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (!response.ok) return null;

      const data = await response.json();

      return data.authenticated ? data.user || "user" : null;
    } catch (error) {
      // Network failure is not proof the token is bad; keep it and let the
      // first data call surface the real error.
      return "user";
    }
  }

  window.AniQuestAuth = {
    ready,

    get user() {
      return user;
    },

    apiFetch(input, init = {}) {
      const headers = new Headers(init.headers || {});

      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }

      return fetch(input, { ...init, headers });
    },

    requireLogin(message) {
      clearToken();
      showLogin(message || "Sign in to continue.");
    }
  };

  form.addEventListener("submit", async event => {
    event.preventDefault();

    errorEl.textContent = "";
    submitBtn.disabled = true;
    submitBtn.textContent = "checking…";

    try {
      const response = await fetch(`${API}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: userInput.value.trim(),
          password: passInput.value
        })
      });

      if (!response.ok) {
        errorEl.textContent =
          response.status === 401
            ? "Wrong username or password."
            : `Login failed (HTTP ${response.status}).`;
        passInput.value = "";
        passInput.focus();
        return;
      }

      const data = await response.json();

      token = data.token || "";
      localStorage.setItem(STORAGE_KEY, token);

      if (resolved) {
        location.reload();
        return;
      }

      signedIn(data.user);
      finish();
    } catch (error) {
      errorEl.textContent = "API unreachable. Try again in a moment.";
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "unlock";
    }
  });

  logoutBtn?.addEventListener("click", () => {
    clearToken();
    location.reload();
  });

  (async () => {
    if (token) {
      const name = await sessionUser();

      if (name) {
        signedIn(name);
        finish();
        return;
      }

      clearToken();
    }

    showLogin("");
  })();
})();
