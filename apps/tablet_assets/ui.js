/* Tríade Ω tablet console. No remote private runtime, secrets or arbitrary code. */
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = {
    currentPlan: null,
    installer: null,
    storageKey: "triade-omega-public-plan-history-v1"
  };

  function message(text, isError) {
    const node = byId("message");
    node.textContent = text || "";
    node.classList.toggle("error", Boolean(isError));
  }

  async function getJSON(path, init) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12500);
    try {
      const response = await fetch(path, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        signal: controller.signal,
        ...init
      });
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      return await response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  async function loadStatus() {
    const pill = byId("online-pill");
    const label = byId("online-label");
    const metric = byId("gateway-state");
    const subtitle = byId("gateway-subtitle");
    pill.classList.remove("healthy", "unhealthy");
    label.textContent = "Verificando enlace";
    try {
      const status = await getJSON("/api/public/status");
      if (status.operativo !== true || status.runtime_original_conectado !== false) {
        throw new Error("Respuesta no compatible con modo observatorio");
      }
      pill.classList.add("healthy");
      label.textContent = "Observatorio en línea";
      metric.textContent = "Conectado";
      subtitle.textContent = "MCP público en Render · lectura verificada";
    } catch (error) {
      pill.classList.add("unhealthy");
      label.textContent = "Sin conexión";
      metric.textContent = "No disponible";
      subtitle.textContent = "No se pudo consultar el servidor · intenta actualizar";
    }
  }

  async function loadCode() {
    const sha = byId("commit-sha");
    const status = byId("commit-status");
    const source = byId("commit-source");
    const link = byId("commit-link");
    sha.textContent = "Consultando…";
    status.textContent = "Verificando";
    source.textContent = "—";
    link.href = "https://github.com/WatabooColosus/triadees";
    link.textContent = "Ver repositorio público ↗";
    link.classList.add("disabled");
    try {
      const data = await getJSON("/api/public/code");
      if (data.verified && /^[a-fA-F0-9]{40}$/.test(data.main_commit || "")) {
        const proof = "https://github.com/WatabooColosus/triadees/commit/" + data.main_commit;
        sha.textContent = data.main_commit.slice(0, 10);
        status.textContent = "Verificado";
        source.textContent = data.source === "public_github_atom" ? "GitHub Atom" : "GitHub API";
        link.href = proof;
        link.textContent = "Ver commit verificado ↗";
        link.classList.remove("disabled");
      } else {
        sha.textContent = "No confirmado";
        status.textContent = "Fuente no disponible";
        source.textContent = "Sin evidencia";
      }
    } catch (error) {
      sha.textContent = "No confirmado";
      status.textContent = "Sin conexión";
      source.textContent = "Sin evidencia";
    }
  }

  function safeStorage(action) {
    try {
      return action();
    } catch (error) {
      return null;
    }
  }

  function loadHistory() {
    const value = safeStorage(() => localStorage.getItem(state.storageKey));
    if (!value) return [];
    try {
      const parsed = JSON.parse(value);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((item) => item && typeof item.objetivo === "string"
        && item.objetivo.length > 0 && item.objetivo.length <= 500
        && typeof item.created === "number").slice(0, 10);
    } catch (error) {
      return [];
    }
  }

  function renderHistory() {
    const root = byId("history-list");
    root.replaceChildren();
    const history = loadHistory();
    if (!history.length) {
      const p = document.createElement("p");
      p.className = "history-empty";
      p.textContent = "Todavía no hay planes guardados.";
      root.append(p);
      return;
    }
    history.forEach((entry) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "history-item";
      button.title = "Volver a utilizar esta misión";
      const wrapper = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = entry.objetivo;
      const timestamp = document.createElement("small");
      timestamp.textContent = new Date(entry.created).toLocaleString("es-CO", {
        day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"
      });
      wrapper.append(name, timestamp);
      const arrow = document.createElement("span");
      arrow.textContent = "↗";
      arrow.setAttribute("aria-hidden", "true");
      button.append(wrapper, arrow);
      button.addEventListener("click", () => {
        const textarea = byId("objective");
        textarea.value = entry.objetivo;
        updateCounter();
        byId("laboratorio").scrollIntoView({ behavior: "smooth" });
        textarea.focus({ preventScroll: true });
        message("Misión recuperada del historial local. Pulsa Generar para evaluarla.", false);
      });
      root.append(button);
    });
  }

  function saveLocalPlan(plan) {
    const history = loadHistory().filter((item) => item.objetivo !== plan.objetivo);
    history.unshift({ objetivo: plan.objetivo, created: Date.now() });
    safeStorage(() => localStorage.setItem(state.storageKey, JSON.stringify(history.slice(0, 10))));
    renderHistory();
  }

  function updateCounter() {
    const field = byId("objective");
    byId("char-counter").textContent = String(field.value.length) + " / 500";
  }

  function displayPlan(plan) {
    state.currentPlan = plan;
    byId("result-empty").hidden = true;
    byId("result-content").hidden = false;
    byId("result-mode").textContent = "PLAN ESTRUCTURADO";
    byId("result-objective").textContent = plan.objetivo || "";
    byId("result-central").textContent = plan.neurona_central || "";
    byId("result-emotional").textContent = plan.hipotalamo_emocional || "";
    byId("result-storage").textContent = plan.bodega || "";
    byId("result-gates").textContent = "Pruebas de aceptación: "
      + (Array.isArray(plan.gates) ? plan.gates.join(" · ") : "sin especificar");
  }

  async function generatePlan(event) {
    event.preventDefault();
    const objective = byId("objective").value.trim();
    if (!objective || objective.length > 500) {
      message("Escribe una misión entre 1 y 500 caracteres.", true);
      return;
    }
    const button = byId("plan-button");
    button.disabled = true;
    button.textContent = "Consultando núcleos…";
    message("Procesando la misión con la herramienta pública de planificación…", false);
    try {
      const plan = await getJSON("/api/public/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objetivo: objective })
      });
      if (plan.ejecutado !== false || plan.objetivo !== objective) {
        throw new Error("La API no devolvió el plan público esperado");
      }
      displayPlan(plan);
      saveLocalPlan(plan);
      message("Plan recibido. No se ejecutó ningún worker ni se escribió en Drive.", false);
      if (window.innerWidth < 760) {
        byId("result-panel").scrollIntoView({ behavior: "smooth", block: "center" });
      }
    } catch (error) {
      message("No fue posible completar la misión: " + String(error.message || error) + ".", true);
    } finally {
      button.disabled = false;
      button.textContent = "Generar plan triádico ✧";
    }
  }

  async function copyPlan() {
    if (!state.currentPlan) return;
    const plan = state.currentPlan;
    const text = [
      "TRÍADE Ω · PLAN PÚBLICO",
      "Objetivo: " + plan.objetivo,
      "Neurona Central: " + plan.neurona_central,
      "Hipotálamo: " + plan.hipotalamo_emocional,
      "Bodega: " + plan.bodega,
      "Pruebas: " + (plan.gates || []).join(", "),
      "Ejecución real: NO · Bodega original: NO CONECTADA"
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      message("Plan copiado al portapapeles.", false);
    } catch (error) {
      message("Tu navegador no permitió copiar. Puedes seleccionar el texto del plan.", true);
    }
  }

  function initInstall() {
    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      state.installer = event;
      byId("install-button").hidden = false;
    });
    byId("install-button").addEventListener("click", async () => {
      if (!state.installer) return;
      state.installer.prompt();
      await state.installer.userChoice;
      state.installer = null;
      byId("install-button").hidden = true;
    });
    window.addEventListener("appinstalled", () => {
      byId("install-button").hidden = true;
      state.installer = null;
    });
  }

  function initNavigation() {
    const links = Array.from(document.querySelectorAll(".nav-link"));
    links.forEach((link) => {
      link.addEventListener("click", () => {
        links.forEach((other) => other.classList.remove("active"));
        link.classList.add("active");
      });
    });
  }

  function boot() {
    byId("objective").addEventListener("input", updateCounter);
    byId("plan-form").addEventListener("submit", generatePlan);
    byId("refresh-all").addEventListener("click", () => {
      loadStatus();
      loadCode();
    });
    byId("refresh-code").addEventListener("click", loadCode);
    byId("copy-plan").addEventListener("click", copyPlan);
    byId("clear-history").addEventListener("click", () => {
      safeStorage(() => localStorage.removeItem(state.storageKey));
      renderHistory();
      message("Se borró únicamente el historial local de este navegador.", false);
    });
    initInstall();
    initNavigation();
    updateCounter();
    renderHistory();
    loadStatus();
    loadCode();
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
