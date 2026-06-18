(() => {
  "use strict";

  const ingressPath = document.querySelector('meta[name="ingress-path"]')?.content || "";
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const jobsViewVisible = Boolean(document.getElementById("jobs-table-body"));
  const jobsRefreshIntervalMs = jobsViewVisible ? 500 : 2500;
  const themeStorageKey = "media-web-downloader-theme";
  const historyMobileViewStorageKey = "media-web-downloader-history-mobile-view";
  const playerSettingsStorageKey = "media-web-downloader-player-settings";
  const playerPositionsStorageKey = "media-web-downloader-player-positions";
  const restorePathStorageKey = "media-web-downloader-restore-path";
  let intentionalNavigation = false;
  let allowedHosts = new Set();
  try {
    allowedHosts = new Set(JSON.parse(document.getElementById("allowed-hosts")?.textContent || "[]"));
  } catch (error) {
    console.error("Nie można odczytać listy obsługiwanych domen:", error);
  }

  const route = (path) => `${ingressPath}${path}`;

  const currentInternalLocation = () => {
    const pathname = window.location.pathname;
    const internalPath = ingressPath && pathname.startsWith(ingressPath)
      ? pathname.slice(ingressPath.length) || "/"
      : pathname || "/";
    return `${internalPath}${window.location.search}`;
  };

  const restorePathAfterRefresh = () => {
    let restorePath = "";
    try {
      restorePath = sessionStorage.getItem(restorePathStorageKey) || "";
      sessionStorage.removeItem(restorePathStorageKey);
    } catch {
      return;
    }
    if (currentInternalLocation() === "/" && restorePath && restorePath !== "/") {
      window.location.replace(route(restorePath));
    }
  };

  restorePathAfterRefresh();

  document.addEventListener("click", (event) => {
    if (event.target.closest("a[href]")) intentionalNavigation = true;
  }, true);

  document.addEventListener("submit", () => {
    intentionalNavigation = true;
  }, true);

  window.addEventListener("beforeunload", () => {
    try {
      const currentPath = currentInternalLocation();
      if (currentPath !== "/" && !intentionalNavigation) {
        sessionStorage.setItem(restorePathStorageKey, currentPath);
      } else {
        sessionStorage.removeItem(restorePathStorageKey);
      }
    } catch {
      // Session storage can be unavailable in hardened WebViews.
    }
  });

  const preferredTheme = () => (
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light"
  );

  const storedTheme = () => {
    try {
      const theme = localStorage.getItem(themeStorageKey);
      return theme === "dark" || theme === "light" ? theme : null;
    } catch {
      return null;
    }
  };

  const syncThemeToggle = (theme) => {
    const button = document.querySelector("[data-theme-toggle]");
    if (!button) return;
    const nextTheme = theme === "dark" ? "jasny" : "ciemny";
    button.setAttribute("aria-label", `Zmień motyw na ${nextTheme}`);
    button.setAttribute("title", `Zmień motyw na ${nextTheme}`);
    button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
  };

  const applyTheme = (theme, persist = false) => {
    document.documentElement.setAttribute("data-bs-theme", theme);
    document.documentElement.style.colorScheme = theme;
    if (persist) {
      try {
        localStorage.setItem(themeStorageKey, theme);
      } catch {
        // Browser storage can be unavailable in hardened WebViews.
      }
    }
    syncThemeToggle(theme);
  };

  applyTheme(storedTheme() || document.documentElement.getAttribute("data-bs-theme") || preferredTheme());

  document.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
    applyTheme(currentTheme === "dark" ? "light" : "dark", true);
  });

  const navbarMenu = document.getElementById("app-navbar-menu");
  navbarMenu?.addEventListener("click", (event) => {
    if (!event.target.closest(".nav-link") || !navbarMenu.classList.contains("show")) return;
    window.bootstrap?.Collapse.getOrCreateInstance(navbarMenu, { toggle: false }).hide();
  });

  const toastContainer = () => {
    let container = document.querySelector(".app-toast-container");
    if (container) return container;
    container = document.createElement("div");
    container.className = "toast-container app-toast-container position-fixed top-0 end-0 p-3";
    document.querySelector("main")?.prepend(container);
    return container;
  };

  const showAppToast = (message, { type = "info", actionHref = "", actionLabel = "" } = {}) => {
    const toast = document.createElement("div");
    const color = {
      success: "text-bg-success",
      warning: "text-bg-warning",
      danger: "text-bg-danger",
      info: "text-bg-info",
    }[type] || "text-bg-primary";
    toast.className = `toast app-toast ${color}`;
    toast.setAttribute("role", type === "danger" ? "alert" : "status");
    toast.setAttribute("aria-live", type === "danger" ? "assertive" : "polite");
    toast.setAttribute("aria-atomic", "true");
    toast.dataset.bsDelay = "6500";
    const wrapper = document.createElement("div");
    wrapper.className = "d-flex";
    const body = document.createElement("div");
    body.className = "toast-body";
    const label = document.createElement("span");
    label.textContent = message;
    body.append(label);
    if (actionHref && actionLabel) {
      const action = document.createElement("a");
      action.className = "toast-action-link";
      action.href = actionHref;
      action.textContent = actionLabel;
      body.append(action);
    }
    const close = document.createElement("button");
    close.className = `btn-close${["success", "danger"].includes(type) ? " btn-close-white" : ""} me-2 m-auto`;
    close.type = "button";
    close.dataset.bsDismiss = "toast";
    close.setAttribute("aria-label", "Zamknij");
    wrapper.append(body, close);
    toast.append(wrapper);
    toastContainer().append(toast);
    window.bootstrap?.Toast?.getOrCreateInstance(toast)?.show();
    toast.addEventListener("hidden.bs.toast", () => toast.remove());
  };

  document.querySelectorAll("[data-app-toast]").forEach((toastNode) => {
    window.bootstrap?.Toast?.getOrCreateInstance(toastNode)?.show();
  });

  const text = (tag, value, className = "") => {
    const node = document.createElement(tag);
    node.textContent = value ?? "";
    if (className) node.className = className;
    return node;
  };

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);

  const downloadTypeLabel = (downloadType) => ({
    best: "najlepsza",
    video: "najlepsza",
    "video-1080": "1080p",
    "video-720": "720p",
    "video-360": "360p",
    audio: "audio MP3",
    format: "konkretny format",
    live: "live",
  })[downloadType] || downloadType;

  const isValidMediaUrl = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && allowedHosts.has(url.hostname.toLowerCase());
    } catch {
      return false;
    }
  };

  const pastedUrls = (value) => {
    const urls = [];
    const seen = new Set();
    String(value || "").split(/[\n\r,;]+/).map((item) => item.trim()).filter(Boolean).forEach((item) => {
      if (seen.has(item)) return;
      seen.add(item);
      urls.push(item);
    });
    return urls;
  };

  const historyMobileViewRoot = document.querySelector("[data-history-mobile-view-root]");
  const historyMobileViewButtons = Array.from(document.querySelectorAll("[data-history-mobile-view]"));
  if (historyMobileViewRoot && historyMobileViewButtons.length) {
    const storedHistoryMobileView = () => {
      try {
        return localStorage.getItem(historyMobileViewStorageKey) === "compact" ? "compact" : "cards";
      } catch {
        return "cards";
      }
    };

    const setHistoryMobileView = (view, persist = false) => {
      const normalizedView = view === "compact" ? "compact" : "cards";
      historyMobileViewRoot.classList.toggle("history-mobile-compact", normalizedView === "compact");
      historyMobileViewButtons.forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.historyMobileView === normalizedView));
      });
      if (persist) {
        try {
          localStorage.setItem(historyMobileViewStorageKey, normalizedView);
        } catch {
          // Browser storage can be unavailable in hardened WebViews.
        }
      }
    };

    historyMobileViewButtons.forEach((button) => {
      button.addEventListener("click", () => setHistoryMobileView(button.dataset.historyMobileView, true));
    });
    setHistoryMobileView(storedHistoryMobileView());
  }

  document.querySelectorAll(".url-form").forEach((form) => {
    const input = form.querySelector(".media-url");
    const feedback = form.querySelector(".invalid-feedback");
    const bulkReview = form.querySelector("[data-bulk-url-review]");
    const bulkList = form.querySelector("[data-bulk-url-list]");
    const bulkSummary = form.querySelector("[data-bulk-url-summary]");
    const copyInvalidUrls = form.querySelector("[data-bulk-url-copy-invalid]");
    const removeInvalidUrls = form.querySelector("[data-bulk-url-remove-invalid]");
    const syncTextareaHeight = () => {
      if (!(input instanceof HTMLTextAreaElement)) return;
      input.style.height = "auto";
      input.style.height = `${Math.max(input.scrollHeight, 54)}px`;
    };
    const selectedBulkUrls = () => Array.from(
      bulkList?.querySelectorAll(".bulk-url-select:checked") || []
    ).map((checkbox) => checkbox.value);
    const syncBulkSummary = () => {
      if (!bulkSummary || !bulkList) return;
      const total = bulkList.querySelectorAll(".bulk-url-select").length;
      const selected = selectedBulkUrls().length;
      const invalid = bulkList.querySelectorAll(".bulk-url-item-invalid").length;
      bulkSummary.textContent = total > 1 ? `Wybrano ${selected} z ${total} linków.` : "";
      if (copyInvalidUrls instanceof HTMLButtonElement) copyInvalidUrls.disabled = invalid === 0;
      if (removeInvalidUrls instanceof HTMLButtonElement) removeInvalidUrls.disabled = invalid === 0;
    };
    const setBulkUrls = (urls) => {
      if (!(input instanceof HTMLTextAreaElement)) return;
      input.value = urls.join("\n");
      syncTextareaHeight();
      renderBulkUrlReview();
    };
    const renderBulkUrlReview = () => {
      if (!bulkReview || !bulkList) return;
      const urls = pastedUrls(input?.value || "");
      bulkReview.classList.toggle("d-none", urls.length <= 1);
      bulkList.replaceChildren();
      urls.forEach((url, index) => {
        const valid = isValidMediaUrl(url);
        const label = document.createElement("label");
        label.className = `bulk-url-item${valid ? "" : " bulk-url-item-invalid"}`;
        const checkbox = document.createElement("input");
        checkbox.className = "form-check-input bulk-url-select";
        checkbox.type = "checkbox";
        checkbox.value = url;
        checkbox.checked = valid;
        checkbox.disabled = !valid;
        checkbox.addEventListener("change", syncBulkSummary);
        const body = document.createElement("span");
        body.className = "bulk-url-text";
        body.textContent = url;
        const status = document.createElement("span");
        status.className = "bulk-url-status";
        status.textContent = valid ? `Link ${index + 1}` : "Nieobsługiwany lub niepoprawny URL";
        const remove = document.createElement("button");
        remove.className = "bulk-url-remove";
        remove.type = "button";
        remove.setAttribute("aria-label", `Usuń link ${index + 1}`);
        remove.title = "Usuń link";
        remove.textContent = "×";
        remove.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          const nextUrls = pastedUrls(input?.value || "").filter((item) => item !== url);
          setBulkUrls(nextUrls);
        });
        body.append(status);
        label.append(checkbox, body, remove);
        bulkList.append(label);
      });
      syncBulkSummary();
    };
    form.querySelectorAll("[data-bulk-url-select]").forEach((button) => {
      button.addEventListener("click", () => {
        const shouldSelect = button.dataset.bulkUrlSelect === "all";
        bulkList?.querySelectorAll(".bulk-url-select:not(:disabled)").forEach((checkbox) => {
          checkbox.checked = shouldSelect;
        });
        syncBulkSummary();
      });
    });
    copyInvalidUrls?.addEventListener("click", async () => {
      const invalidUrls = pastedUrls(input?.value || "").filter((url) => !isValidMediaUrl(url));
      if (!invalidUrls.length) return;
      try {
        await copyTextToClipboard(invalidUrls.join("\n"));
        copyInvalidUrls.textContent = "Skopiowano";
        window.setTimeout(() => {
          copyInvalidUrls.textContent = "Kopiuj błędne";
        }, 1400);
      } catch (error) {
        console.error("Nie można skopiować błędnych URL-i:", error);
      }
    });
    removeInvalidUrls?.addEventListener("click", () => {
      setBulkUrls(pastedUrls(input?.value || "").filter(isValidMediaUrl));
    });
    input?.addEventListener("input", () => {
      syncTextareaHeight();
      renderBulkUrlReview();
    });
    input?.addEventListener("paste", () => setTimeout(() => {
      syncTextareaHeight();
      renderBulkUrlReview();
    }, 0));
    form.addEventListener("submit", (event) => {
      const quickDownload = event.submitter instanceof HTMLElement
        && event.submitter.matches("[data-quick-download-submit]");
      const detectedUrls = pastedUrls(input?.value || "");
      const urls = detectedUrls.length > 1 ? selectedBulkUrls() : detectedUrls;
      const invalidUrls = urls.filter((url) => !isValidMediaUrl(url));
      if (!urls.length || invalidUrls.length || (quickDownload && urls.length !== 1)) {
        event.preventDefault();
        event.stopPropagation();
        input?.classList.add("is-invalid");
        if (feedback) {
          feedback.textContent = !urls.length
            ? "Wklej co najmniej jeden adres URL."
            : invalidUrls.length
              ? `Niepoprawne URL-e: ${invalidUrls.join(", ")}`
              : "Szybkie pobieranie obsługuje jeden link naraz.";
        }
        return;
      }
      if (input instanceof HTMLTextAreaElement) input.value = urls.join("\n");
      if (feedback) {
        feedback.textContent = "Wklej poprawny adres HTTP lub HTTPS z obsługiwanej domeny YouTube, Instagram, Kick albo Twitch.";
      }
      input?.classList.remove("is-invalid");
      syncTextareaHeight();
      form.classList.add("was-validated");
      const button = form.querySelector(
        quickDownload ? ".quick-download-submit" : ".analyze-submit"
      );
      form.querySelectorAll('button[type="submit"]').forEach((submitButton) => {
        submitButton.setAttribute("disabled", "disabled");
        submitButton.setAttribute("aria-disabled", "true");
      });
      button?.querySelector(".spinner-border")?.classList.remove("d-none");
      const label = button?.querySelector(
        quickDownload ? ".quick-download-submit-label" : ".analyze-submit-label"
      );
      if (label) label.textContent = "Analizuję...";
      if (label && quickDownload) label.textContent = "Dodaję...";
      const loading = form.querySelector(".analyze-loading");
      if (loading) {
        loading.innerHTML = quickDownload
          ? '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Dodaję pobieranie do kolejki.'
          : '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Analizuję materiał przez yt-dlp. To może potrwać chwilę.';
        loading.classList.remove("d-none");
      }
    });
  });

  const formatMediaTime = (seconds) => {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return "0:00";
    const rounded = Math.floor(value);
    const hours = Math.floor(rounded / 3600);
    const minutes = Math.floor((rounded % 3600) / 60);
    const rest = rounded % 60;
    return hours
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`
      : `${minutes}:${String(rest).padStart(2, "0")}`;
  };

  const playerIcon = (name) => {
    const icons = {
      captions: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v8a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 14.5v-8Zm2.5-.7a.7.7 0 0 0-.7.7v8c0 .39.31.7.7.7h11a.7.7 0 0 0 .7-.7v-8a.7.7 0 0 0-.7-.7h-11ZM7.5 10.1c0-1.2.95-2.1 2.25-2.1.78 0 1.38.25 1.85.7l-.8 1.02c-.3-.25-.6-.42-1.02-.42-.58 0-.95.35-.95.8v.8c0 .45.37.8.95.8.42 0 .72-.17 1.02-.42l.8 1.02c-.47.45-1.07.7-1.85.7-1.3 0-2.25-.9-2.25-2.1v-.8Zm5.2 0c0-1.2.95-2.1 2.25-2.1.78 0 1.38.25 1.85.7l-.8 1.02c-.3-.25-.6-.42-1.02-.42-.58 0-.95.35-.95.8v.8c0 .45.37.8.95.8.42 0 .72-.17 1.02-.42l.8 1.02c-.47.45-1.07.7-1.85.7-1.3 0-2.25-.9-2.25-2.1v-.8Z"/></svg>',
      fullscreen: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9V5h4v2H7v2H5Zm10-4h4v4h-2V7h-2V5ZM7 15v2h2v2H5v-4h2Zm10 2v-2h2v4h-4v-2h2Z"/></svg>',
      fullscreenExit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5v4H5V7h2V5h2Zm8 0v2h2v2h-4V5h2ZM5 15h4v4H7v-2H5v-2Zm14 0v2h-2v2h-2v-4h4Z"/></svg>',
      copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7a3 3 0 0 1 3-3h6a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-1v1a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3h1V7Zm3-1.2A1.2 1.2 0 0 0 9.8 7v6a1.2 1.2 0 0 0 1.2 1.2h6a1.2 1.2 0 0 0 1.2-1.2V7A1.2 1.2 0 0 0 17 5.8h-6ZM7 9.8A1.2 1.2 0 0 0 5.8 11v6A1.2 1.2 0 0 0 7 18.2h6a1.2 1.2 0 0 0 1.2-1.2v-1H11a3 3 0 0 1-3-3V9.8H7Z"/></svg>',
      debug: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.6 5.2 4 8.8l3.6 3.6-1.25 1.25L1.5 8.8l4.85-4.85L7.6 5.2Zm8.8 0 1.25-1.25L22.5 8.8l-4.85 4.85-1.25-1.25L20 8.8l-3.6-3.6ZM14.2 3.5h1.9l-6.3 17H7.9l6.3-17Z"/></svg>',
      embed: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v13a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5v-13Zm2.5-.7a.7.7 0 0 0-.7.7v2.7h12.4V5.5a.7.7 0 0 0-.7-.7h-11Zm-.7 5.2v8.5c0 .39.31.7.7.7h11a.7.7 0 0 0 .7-.7V10H5.8Zm4.8 2.2 1.25 1.25L10.3 15l1.55 1.55-1.25 1.25L7.8 15l2.8-2.8Zm2.8 0 2.8 2.8-2.8 2.8-1.25-1.25L13.7 15l-1.55-1.55 1.25-1.25Z"/></svg>',
      flag: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h9.4l.35 1.35H20v9h-6.4l-.35-1.35H6.8v7H5V4Zm1.8 1.8v5.4h7.85L15 12.55h3.2v-5.4h-4.85L13 5.8H6.8Z"/></svg>',
      linkTime: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 7.5h2V12l3.5 2.1-1 1.65-4.5-2.7V7.5Zm2.5-5a9.5 9.5 0 1 1 0 19 9.5 9.5 0 0 1 0-19Zm0 1.8a7.7 7.7 0 1 0 0 15.4 7.7 7.7 0 0 0 0-15.4Z"/></svg>',
      loop: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h8.6l-2-2L15 3.6 19.4 8 15 12.4 13.6 11l2-2H7a3 3 0 0 0-3 3v1H2v-1a5 5 0 0 1 5-5Zm10 10H8.4l2 2L9 20.4 4.6 16 9 11.6l1.4 1.4-2 2H17a3 3 0 0 0 3-3v-1h2v1a5 5 0 0 1-5 5Z"/></svg>',
      mini: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5v-11Zm2.5-.7a.7.7 0 0 0-.7.7v11c0 .39.31.7.7.7h11a.7.7 0 0 0 .7-.7v-11a.7.7 0 0 0-.7-.7h-11Zm4.3 6.2h5.4v3.5h-5.4V12Z"/></svg>',
      pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3v14H7V5Zm7 0h3v14h-3V5Z"/></svg>',
      play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.4v13.2L18.4 12 8 5.4Z"/></svg>',
      settings: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m19.2 13.35 1.55 1.2-1.8 3.1-1.85-.75a7.7 7.7 0 0 1-1.45.85L15.4 19.7h-3.6l-.25-1.95a7.7 7.7 0 0 1-1.45-.85l-1.85.75-1.8-3.1 1.55-1.2a6.5 6.5 0 0 1 0-1.7l-1.55-1.2 1.8-3.1 1.85.75c.45-.33.93-.62 1.45-.85l.25-1.95h3.6l.25 1.95c.52.23 1 .52 1.45.85l1.85-.75 1.8 3.1-1.55 1.2a6.5 6.5 0 0 1 0 1.7ZM13.6 9.4a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2Z"/></svg>',
      stats: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v2H4V5Zm0 4h10v2H4V9Zm0 4h16v2H4v-2Zm0 4h10v2H4v-2Zm13-8h3v2h-3V9Zm0 8h3v2h-3v-2Z"/></svg>',
      volume: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.2h3.4L12 5.3v13.4l-4.6-3.9H4V9.2Zm11.1-.7a5.2 5.2 0 0 1 0 7l-1.25-1.25a3.4 3.4 0 0 0 0-4.5L15.1 8.5Zm2.7-2.35a8.7 8.7 0 0 1 0 11.7l-1.25-1.25a6.9 6.9 0 0 0 0-9.2l1.25-1.25Z"/></svg>',
      volumeOff: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.2h3.4L12 5.3v13.4l-4.6-3.9H4V9.2Zm10.25.2L16 11.15l1.75-1.75 1.25 1.25-1.75 1.75L19 14.15l-1.25 1.25L16 13.65l-1.75 1.75L13 14.15l1.75-1.75L13 10.65l1.25-1.25Z"/></svg>',
    };
    return icons[name] || "";
  };

  const customPlayerButton = (label, icon, className = "") => {
    const button = document.createElement("button");
    button.className = `custom-player-button ${className}`.trim();
    button.type = "button";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.innerHTML = icon;
    return button;
  };

  const supportsFullscreen = (element) => (
    Boolean(element?.requestFullscreen) ||
    Boolean(element?.webkitRequestFullscreen)
  );

  const fullscreenElement = () => document.fullscreenElement || document.webkitFullscreenElement || null;

  const requestFullscreen = (element) => {
    if (element.requestFullscreen) return element.requestFullscreen();
    if (element.webkitRequestFullscreen) return element.webkitRequestFullscreen();
    return Promise.resolve();
  };

  const exitFullscreen = () => {
    if (document.exitFullscreen) return document.exitFullscreen();
    if (document.webkitExitFullscreen) return document.webkitExitFullscreen();
    return Promise.resolve();
  };

  let activeCustomPlayer = null;
  const isEditableShortcutTarget = (target) => {
    if (!(target instanceof Element)) return false;
    return Boolean(
      target.closest("input, textarea, select, button, [contenteditable='true']")
    );
  };

  const readJsonStorage = (key, fallback) => {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      const value = JSON.parse(raw);
      return value && typeof value === "object" ? value : fallback;
    } catch {
      return fallback;
    }
  };

  const writeJsonStorage = (key, value) => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Browser storage can be unavailable in hardened WebViews.
    }
  };

  const readPlayerSettings = () => ({
    volume: 1,
    muted: false,
    playbackRate: 1,
    loop: false,
    autoplayNext: false,
    fitMode: "contain",
    ...readJsonStorage(playerSettingsStorageKey, {}),
  });

  const writePlayerSettings = (settings) => {
    const fitMode = settings.fitMode === "cover" ? "cover" : "contain";
    const normalized = {
      volume: Math.min(1, Math.max(0, Number(settings.volume) || 0)),
      muted: Boolean(settings.muted),
      playbackRate: clampPlaybackRate(settings.playbackRate),
      loop: Boolean(settings.loop),
      autoplayNext: Boolean(settings.autoplayNext),
      fitMode,
    };
    writeJsonStorage(playerSettingsStorageKey, normalized);
  };

  const playerPositionKey = (media) => media.currentSrc || media.src || "";

  const readPlayerPositions = () => readJsonStorage(playerPositionsStorageKey, {});

  const writePlayerPosition = (media) => {
    const key = playerPositionKey(media);
    if (!key || !Number.isFinite(media.duration) || media.duration < 30) return;
    const positions = readPlayerPositions();
    if (media.currentTime > 3 && media.currentTime < media.duration - 3) {
      positions[key] = Math.floor(media.currentTime);
    } else {
      delete positions[key];
    }
    writeJsonStorage(playerPositionsStorageKey, positions);
  };

  const copyPlayerTextToClipboard = async (value) => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const fallback = document.createElement("textarea");
    fallback.value = value;
    fallback.setAttribute("readonly", "readonly");
    fallback.style.position = "fixed";
    fallback.style.opacity = "0";
    document.body.append(fallback);
    fallback.select();
    document.execCommand("copy");
    fallback.remove();
  };

  const createPlayerContextMenuItem = (label, iconName, action) => {
    const button = document.createElement("button");
    button.className = "custom-player-context-item";
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.innerHTML = `<span class="custom-player-context-icon">${playerIcon(iconName)}</span><span>${escapeHtml(label)}</span>`;
    button.addEventListener("click", action);
    return button;
  };

  const sourceLabelFromMedia = (media) => {
    const source = media.currentSrc || media.querySelector("source")?.src || "";
    if (!source) return "N/A";
    try {
      const url = new URL(source, window.location.href);
      const filename = url.pathname.split("/").filter(Boolean).pop();
      return filename ? decodeURIComponent(filename) : url.href;
    } catch {
      return source;
    }
  };

  const bufferEndForMedia = (media) => {
    try {
      const ranges = media.buffered;
      for (let index = 0; index < ranges.length; index += 1) {
        if (ranges.start(index) <= media.currentTime && ranges.end(index) >= media.currentTime) {
          return ranges.end(index);
        }
      }
      return ranges.length ? ranges.end(ranges.length - 1) : null;
    } catch {
      return null;
    }
  };

  const mediaNetworkStateLabel = (state) => ({
    0: "empty",
    1: "idle",
    2: "loading",
    3: "no source",
  }[state] || "N/A");

  const mediaReadyStateLabel = (state) => ({
    0: "nothing",
    1: "metadata",
    2: "current data",
    3: "future data",
    4: "enough data",
  }[state] || "N/A");

  const clampPlaybackRate = (value) => Math.min(3, Math.max(0.25, Number(value) || 1));

  const playbackRateLabel = (value) => {
    const rounded = Math.round(clampPlaybackRate(value) * 100) / 100;
    return `${String(rounded).replace(/\.?0+$/, "")}x`;
  };

  const formatPlayerBytes = (value) => {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes <= 0) return "brak danych";
    const units = ["B", "KB", "MB", "GB"];
    let size = bytes;
    for (const unit of units) {
      if (size < 1024 || unit === units[units.length - 1]) return `${size.toFixed(1)} ${unit}`;
      size /= 1024;
    }
    return "brak danych";
  };

  const mediaResourceTiming = (media) => {
    const source = media.currentSrc || media.querySelector("source")?.src || "";
    if (!source || !window.performance?.getEntriesByName) return null;
    const entries = window.performance.getEntriesByName(source).filter((entry) => entry.entryType === "resource");
    return entries.length ? entries[entries.length - 1] : null;
  };

  const connectionSpeedLabel = (media) => {
    const timing = mediaResourceTiming(media);
    const bytes = Number(timing?.transferSize || timing?.encodedBodySize || 0);
    const durationMs = Number(timing?.duration || 0);
    if (bytes > 0 && durationMs > 0) {
      return `${((bytes * 8) / durationMs / 1000).toFixed(2)} Mbps`;
    }
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (connection?.downlink) {
      const type = connection.effectiveType ? ` (${connection.effectiveType})` : "";
      return `${connection.downlink} Mbps${type}`;
    }
    return "brak danych w API przeglądarki";
  };

  const networkActivityLabel = (media, activity) => {
    const timing = mediaResourceTiming(media);
    const bytes = Number(timing?.transferSize || timing?.encodedBodySize || activity?.loadedBytes || 0);
    const eventAge = activity?.lastAt ? `${Math.max(0, ((Date.now() - activity.lastAt) / 1000)).toFixed(1)} s temu` : "brak";
    return [
      `${mediaNetworkStateLabel(media.networkState)} / ${mediaReadyStateLabel(media.readyState)}`,
      `event=${activity?.lastEvent || "init"} (${eventAge})`,
      `dane=${formatPlayerBytes(bytes)}`,
    ].join("; ");
  };

  const bufferHealthLabel = (media) => {
    const bufferedEnd = bufferEndForMedia(media);
    if (Number.isFinite(bufferedEnd)) {
      return `${Math.max(0, bufferedEnd - media.currentTime).toFixed(2)} s`;
    }
    if (media.readyState >= 4 && Number.isFinite(media.duration)) {
      return `${Math.max(0, media.duration - media.currentTime).toFixed(2)} s`;
    }
    return `${mediaReadyStateLabel(media.readyState)} / ${mediaNetworkStateLabel(media.networkState)}`;
  };

  const getVideoDebugStats = (player, media, activity = null) => {
    const playbackQuality = typeof media.getVideoPlaybackQuality === "function"
      ? media.getVideoPlaybackQuality()
      : null;
    const decodedFrames = playbackQuality?.totalVideoFrames ?? media.webkitDecodedFrameCount;
    const droppedFrames = playbackQuality?.droppedVideoFrames ?? media.webkitDroppedFrameCount;
    const playerRect = player.getBoundingClientRect();
    const viewport = playerRect.width && playerRect.height
      ? `${Math.round(playerRect.width)}x${Math.round(playerRect.height)}`
      : "N/A";
    const frames = Number.isFinite(decodedFrames)
      ? `${decodedFrames} decoded / ${Number.isFinite(droppedFrames) ? droppedFrames : "N/A"} dropped`
      : "N/A";
    const resolution = media.videoWidth && media.videoHeight
      ? `${media.videoWidth}x${media.videoHeight}`
      : "N/A";
    const source = media.querySelector("source");
    const mimeType = source?.type || "";
    const duration = Number.isFinite(media.duration) ? formatMediaTime(media.duration) : "N/A";
    const current = Number.isFinite(media.currentTime) ? formatMediaTime(media.currentTime) : "N/A";
    const rows = [
      ["Date", new Date().toLocaleString()],
      ["Video ID / Name", player.dataset.videoId || player.dataset.videoTitle || sourceLabelFromMedia(media)],
      ["Viewport / Frames", `${viewport} / ${frames}`],
      ["Current / Optimal Res", `${resolution} / N/A`],
      ["Volume / Normalized", `${media.muted ? "muted" : `${Math.round(media.volume * 100)}%`} / N/A`],
      ["Codecs", mimeType || "N/A"],
      ["Color", "N/A"],
      ["Connection Speed", connectionSpeedLabel(media)],
      ["Network Activity", networkActivityLabel(media, activity)],
      ["Buffer Health", bufferHealthLabel(media)],
      ["Mystery Text", `current=${current}; duration=${duration}; src=${sourceLabelFromMedia(media)}`],
    ];
    return rows;
  };

  const formatVideoDebugStats = (player, media, activity = null) => (
    getVideoDebugStats(player, media, activity)
      .map(([label, value]) => `${label}: ${value || "N/A"}`)
      .join("\n")
  );

  const enhanceCustomPlayer = (player) => {
    const media = player.querySelector(".custom-player-media");
    if (!(media instanceof HTMLMediaElement) || player.dataset.customPlayerReady) return;
    player.dataset.customPlayerReady = "true";
    const storedSettings = readPlayerSettings();
    const storedVolume = Number(storedSettings.volume);
    media.volume = Number.isFinite(storedVolume) ? Math.min(1, Math.max(0, storedVolume)) : 1;
    media.muted = Boolean(storedSettings.muted);
    media.playbackRate = clampPlaybackRate(storedSettings.playbackRate);
    media.loop = Boolean(storedSettings.loop);
    player.classList.toggle("custom-player-fit-cover", storedSettings.fitMode === "cover");
    const isVideo = media instanceof HTMLVideoElement;
    if (isVideo && !player.hasAttribute("tabindex")) {
      player.tabIndex = 0;
      player.setAttribute("aria-keyshortcuts", "Space K J L ArrowLeft ArrowRight ArrowUp ArrowDown M F");
    }

    const progress = document.createElement("input");
    progress.className = "custom-player-range custom-player-progress";
    progress.type = "range";
    progress.min = "0";
    progress.max = "1000";
    progress.value = "0";
    progress.step = "1";
    progress.setAttribute("aria-label", "Postęp odtwarzania");

    const play = customPlayerButton("Odtwórz", playerIcon("play"), "custom-player-play");
    const playSecondary = customPlayerButton(
      "Odtwórz",
      playerIcon("play"),
      "custom-player-play custom-player-play-secondary"
    );
    const mute = customPlayerButton("Wycisz", playerIcon("volume"), "custom-player-mute");
    const captions = customPlayerButton(
      "Napisy",
      playerIcon("captions"),
      "custom-player-captions"
    );
    captions.setAttribute("aria-pressed", "false");
    const settings = customPlayerButton(
      "Ustawienia jakości i prędkości",
      `${playerIcon("settings")}<span class="custom-player-hd-badge">HD</span>`,
      "custom-player-settings"
    );
    const mini = customPlayerButton(
      "Tryb theater",
      playerIcon("mini"),
      "custom-player-mini"
    );
    mini.setAttribute("aria-pressed", "false");
    const fullscreen = customPlayerButton(
      "Pełny ekran",
      playerIcon("fullscreen"),
      "custom-player-fullscreen"
    );
    const inThisVideo = document.createElement("button");
    inThisVideo.className = "custom-player-pill";
    inThisVideo.type = "button";
    inThisVideo.setAttribute("aria-label", "W tym filmie");
    inThisVideo.textContent = "W tym filmie >";
    const settingsPanel = document.createElement("div");
    settingsPanel.className = "custom-player-settings-panel";
    settingsPanel.hidden = true;
    settingsPanel.setAttribute("role", "menu");
    settingsPanel.setAttribute("aria-label", "Ustawienia playera");
    const qualityLabel = escapeHtml(player.dataset.qualityLabel || "Oryginalna");
    settingsPanel.innerHTML = `
      <div class="custom-player-settings-heading">Ustawienia</div>
      <div class="custom-player-settings-row">
        <span>Jakość</span>
        <strong>${qualityLabel}</strong>
      </div>
      <div class="custom-player-settings-group" data-setting-group="speed">
        <div class="custom-player-settings-row">
          <span>Prędkość</span>
          <strong data-speed-value>${playbackRateLabel(media.playbackRate)}</strong>
        </div>
        <div class="custom-player-speed-control">
          <input class="custom-player-range custom-player-speed-slider" type="range" min="0.25" max="3" step="0.05" value="${media.playbackRate}" data-speed-slider aria-label="Prędkość odtwarzania">
          <div class="custom-player-speed-scale" aria-hidden="true">
            <span>0.25x</span>
            <span>1x</span>
            <span>3x</span>
          </div>
        </div>
      </div>
      <label class="custom-player-settings-toggle">
        <span>Zapętlaj</span>
        <input type="checkbox" data-setting-loop>
      </label>
      <label class="custom-player-settings-toggle">
        <span>Auto-play następnego</span>
        <input type="checkbox" data-setting-autoplay-next>
      </label>
      <div class="custom-player-settings-group" data-setting-group="fit">
        <span>Dopasowanie</span>
        <div class="custom-player-settings-options">
          <button type="button" data-fit="contain">Contain</button>
          <button type="button" data-fit="cover">Cover</button>
        </div>
      </div>
    `;
    const time = text("span", "0:00 / 0:00", "custom-player-time");
    const speed = document.createElement("input");
    speed.className = "custom-player-speed";
    speed.type = "range";
    speed.min = "0.25";
    speed.max = "3";
    speed.step = "0.05";
    speed.value = String(media.playbackRate);
    speed.setAttribute("aria-label", "Prędkość odtwarzania");
    const volume = document.createElement("input");
    volume.className = "custom-player-range custom-player-volume";
    volume.type = "range";
    volume.min = "0";
    volume.max = "1";
    volume.step = "0.01";
    volume.value = String(media.volume || 1);
    volume.setAttribute("aria-label", "Głośność");

    const controls = document.createElement("div");
    controls.className = "custom-player-controls";
    const mainRow = document.createElement("div");
    mainRow.className = "custom-player-row custom-player-main-row";
    const leftControls = document.createElement("div");
    leftControls.className = "custom-player-row custom-player-left-controls";
    const volumeGroup = document.createElement("div");
    volumeGroup.className = "custom-player-volume-group";
    volumeGroup.append(mute, volume);
    leftControls.append(play, volumeGroup, time, inThisVideo);
    const rightControls = document.createElement("div");
    rightControls.className = "custom-player-row custom-player-right-controls";
    rightControls.append(playSecondary, captions, settings, mini, fullscreen);
    mainRow.append(leftControls, rightControls);
    controls.append(progress, mainRow, speed);
    player.append(controls);
    player.append(settingsPanel);
    if (!supportsFullscreen(player) && !media.webkitEnterFullscreen) fullscreen.hidden = true;
    const nextUrl = player.dataset.nextUrl || "";
    const settingLoop = settingsPanel.querySelector("[data-setting-loop]");
    const settingAutoplayNext = settingsPanel.querySelector("[data-setting-autoplay-next]");
    const speedSlider = settingsPanel.querySelector("[data-speed-slider]");
    const speedValue = settingsPanel.querySelector("[data-speed-value]");
    const fitButtons = Array.from(settingsPanel.querySelectorAll("[data-fit]"));
    if (settingAutoplayNext instanceof HTMLInputElement) settingAutoplayNext.checked = Boolean(storedSettings.autoplayNext);

    const previewThumbnailUrl = player.dataset.previewThumbnail || "";
    const timelineThumbnails = (() => {
      try {
        const parsed = JSON.parse(player.dataset.previewThumbnails || "[]");
        return Array.isArray(parsed)
          ? parsed
              .map((item) => ({
                time: Number(item.time),
                url: String(item.url || ""),
              }))
              .filter((item) => Number.isFinite(item.time) && item.url)
              .sort((left, right) => left.time - right.time)
          : [];
      } catch {
        return [];
      }
    })();
    let seekPreview = null;
    let seekPreviewImage = null;
    let seekPreviewTime = null;
    if (media instanceof HTMLVideoElement) {
      seekPreview = document.createElement("div");
      seekPreview.className = "custom-player-seek-preview";
      if (previewThumbnailUrl || timelineThumbnails.length) {
        seekPreviewImage = document.createElement("img");
        seekPreviewImage.className = "custom-player-seek-preview-image";
        seekPreviewImage.alt = "";
        seekPreviewImage.loading = "lazy";
        seekPreviewImage.src = timelineThumbnails[0]?.url || previewThumbnailUrl;
        seekPreview.append(seekPreviewImage);
      }
      seekPreviewTime = text("span", "0:00", "custom-player-seek-preview-time");
      seekPreview.append(seekPreviewTime);
      player.append(seekPreview);
    }

    let overlayTime = null;
    let overlayIcon = null;
    if (media instanceof HTMLVideoElement) {
      const overlay = document.createElement("button");
      overlay.className = "custom-player-overlay";
      overlay.type = "button";
      overlay.setAttribute("aria-label", "Odtwórz lub pauzuj");
      overlayIcon = text("span", "\u25b6", "custom-player-overlay-icon");
      overlayTime = text("span", "0:00 / 0:00", "custom-player-overlay-time");
      overlay.append(overlayIcon, overlayTime);
      overlay.addEventListener("click", () => play.click());
      player.append(overlay);
    }

    let contextMenu = null;
    let statsOverlay = null;
    let statsContent = null;
    let statsTimer = null;
    let loopContextItem = null;
    const networkActivity = {
      lastEvent: "init",
      lastAt: Date.now(),
      progressEvents: 0,
      loadedBytes: 0,
    };
    const updateNetworkActivity = (eventName) => {
      networkActivity.lastEvent = eventName;
      networkActivity.lastAt = Date.now();
      if (eventName === "progress") networkActivity.progressEvents += 1;
      const timing = mediaResourceTiming(media);
      const bytes = Number(timing?.transferSize || timing?.encodedBodySize || 0);
      if (bytes > 0) networkActivity.loadedBytes = bytes;
    };
    if (isVideo) {
      contextMenu = document.createElement("div");
      contextMenu.className = "custom-player-context-menu";
      contextMenu.hidden = true;
      contextMenu.setAttribute("role", "menu");
      contextMenu.setAttribute("aria-label", "Menu kontekstowe playera");

      statsOverlay = document.createElement("section");
      statsOverlay.className = "custom-player-stats";
      statsOverlay.hidden = true;
      statsOverlay.setAttribute("aria-label", "Statystyki dla nerdów");
      const statsHeader = document.createElement("div");
      statsHeader.className = "custom-player-stats-header";
      statsHeader.append(text("strong", "Statystyki dla nerdów"));
      const statsClose = document.createElement("button");
      statsClose.className = "custom-player-stats-close";
      statsClose.type = "button";
      statsClose.textContent = "[X]";
      statsClose.setAttribute("aria-label", "Zamknij statystyki");
      statsHeader.append(statsClose);
      statsContent = document.createElement("pre");
      statsContent.className = "custom-player-stats-content";
      statsOverlay.append(statsHeader, statsContent);
      player.append(statsOverlay);
      const copyFeedback = text("div", "", "custom-player-copy-feedback");
      copyFeedback.hidden = true;
      player.append(copyFeedback);
      let copyFeedbackTimer = null;

      const sourceUrlForCopy = () => media.currentSrc || media.querySelector("source")?.src || window.location.href;
      const currentTimeUrl = () => `${sourceUrlForCopy().split("#")[0]}#t=${Math.max(0, Math.floor(media.currentTime || 0))}`;
      const embedCode = () => `<video controls src="${escapeHtml(sourceUrlForCopy())}"></video>`;
      const showPlayerCopyFeedback = (message) => {
        copyFeedback.textContent = message;
        copyFeedback.hidden = false;
        if (copyFeedbackTimer) window.clearTimeout(copyFeedbackTimer);
        copyFeedbackTimer = window.setTimeout(() => {
          copyFeedback.hidden = true;
        }, 1600);
      };
      const copyPlayerValue = async (value, successMessage) => {
        try {
          await copyPlayerTextToClipboard(value || "N/A");
          showPlayerCopyFeedback(successMessage);
          showAppToast(successMessage, { type: "success" });
        } catch (error) {
          console.error("Nie można skopiować danych playera:", error);
          showPlayerCopyFeedback("Nie udało się skopiować danych");
          showAppToast("Nie udało się skopiować danych", { type: "danger" });
        }
      };
      const updateStatsOverlay = () => {
        if (!statsOverlay || !statsContent || statsOverlay.hidden) return;
        statsContent.textContent = formatVideoDebugStats(player, media, networkActivity);
      };
      const setStatsOverlayVisible = (visible) => {
        if (!statsOverlay) return;
        statsOverlay.hidden = !visible;
        if (visible) {
          updateStatsOverlay();
          if (statsTimer) window.clearInterval(statsTimer);
          statsTimer = window.setInterval(updateStatsOverlay, 500);
        } else if (statsTimer) {
          window.clearInterval(statsTimer);
          statsTimer = null;
        }
      };
      const toggleStatsOverlay = () => setStatsOverlayVisible(!statsOverlay || statsOverlay.hidden);
      const hideContextMenu = () => {
        if (contextMenu) contextMenu.hidden = true;
      };
      const positionContextMenu = (clientX, clientY) => {
        if (!contextMenu) return;
        const margin = 8;
        contextMenu.hidden = false;
        contextMenu.style.left = `${margin}px`;
        contextMenu.style.top = `${margin}px`;
        const rect = contextMenu.getBoundingClientRect();
        const left = Math.min(
          Math.max(margin, clientX),
          Math.max(margin, window.innerWidth - rect.width - margin)
        );
        const top = Math.min(
          Math.max(margin, clientY),
          Math.max(margin, window.innerHeight - rect.height - margin)
        );
        contextMenu.style.left = `${left}px`;
        contextMenu.style.top = `${top}px`;
      };
      const syncContextMenuState = () => {
        loopContextItem?.classList.toggle("custom-player-context-item-active", media.loop);
        loopContextItem?.setAttribute("aria-checked", String(media.loop));
      };
      const togglePictureInPicture = async () => {
        try {
          if (document.pictureInPictureElement) {
            await document.exitPictureInPicture();
          } else if (typeof media.requestPictureInPicture === "function") {
            await media.requestPictureInPicture();
          } else {
            mini.click();
          }
        } catch (error) {
          console.error("Nie można uruchomić miniodtwarzacza:", error);
          mini.click();
        }
      };

      loopContextItem = createPlayerContextMenuItem("Odtwarzaj w pętli", "loop", () => {
        media.loop = !media.loop;
        if (settingLoop instanceof HTMLInputElement) settingLoop.checked = media.loop;
        syncSettingsPanel();
        persistSettings();
        syncContextMenuState();
        hideContextMenu();
      });
      loopContextItem.setAttribute("role", "menuitemcheckbox");
      contextMenu.append(
        loopContextItem,
        createPlayerContextMenuItem("Miniodtwarzacz", "mini", () => {
          hideContextMenu();
          togglePictureInPicture();
        }),
        createPlayerContextMenuItem("Kopiuj adres URL filmu", "copy", () => {
          hideContextMenu();
          copyPlayerValue(sourceUrlForCopy(), "Skopiowano adres URL filmu");
        }),
        createPlayerContextMenuItem("Kopiuj adres URL bieżącego momentu", "linkTime", () => {
          hideContextMenu();
          copyPlayerValue(currentTimeUrl(), "Skopiowano adres URL bieżącego momentu");
        }),
        createPlayerContextMenuItem("Skopiuj kod do umieszczenia na stronie", "embed", () => {
          hideContextMenu();
          copyPlayerValue(embedCode(), "Skopiowano kod osadzenia");
        }),
        createPlayerContextMenuItem("Kopiuj informacje debugowania", "debug", () => {
          hideContextMenu();
          copyPlayerValue(formatVideoDebugStats(player, media, networkActivity), "Skopiowano informacje debugowania");
        }),
        createPlayerContextMenuItem("Rozwiąż problem z odtwarzaniem", "flag", () => {
          hideContextMenu();
          showAppToast("Otwórz Diagnostykę, aby sprawdzić ffmpeg, yt-dlp, sieć i miejsce na dysku", {
            type: "info",
            actionHref: route("/diagnostics"),
            actionLabel: "Diagnostyka",
          });
        }),
        createPlayerContextMenuItem("Statystyki dla nerdów", "stats", () => {
          hideContextMenu();
          toggleStatsOverlay();
        })
      );
      player.append(contextMenu);
      statsClose.addEventListener("click", () => setStatsOverlayVisible(false));
      syncContextMenuState();

      player.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        activeCustomPlayer = player;
        settingsPanel.hidden = true;
        settings.classList.remove("custom-player-button-active");
        syncContextMenuState();
        positionContextMenu(event.clientX, event.clientY);
        showControls();
      });
      document.addEventListener("pointerdown", (event) => {
        if (!contextMenu || contextMenu.hidden || contextMenu.contains(event.target)) return;
        hideContextMenu();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || !contextMenu || contextMenu.hidden) return;
        event.preventDefault();
        hideContextMenu();
      });
      window.addEventListener("resize", hideContextMenu);
      document.addEventListener("scroll", hideContextMenu, true);
      media.addEventListener("timeupdate", updateStatsOverlay);
      media.addEventListener("volumechange", updateStatsOverlay);
      media.addEventListener("loadedmetadata", updateStatsOverlay);
      ["loadstart", "loadedmetadata", "progress", "canplay", "canplaythrough", "waiting", "stalled", "suspend", "playing", "emptied"].forEach((eventName) => {
        media.addEventListener(eventName, () => {
          updateNetworkActivity(eventName);
          updateStatsOverlay();
        });
      });
    }

    let controlsTimer = null;
    let seeking = false;
    const updateRangeFill = (range, percent, property) => {
      range.style.setProperty(property, `${Math.min(100, Math.max(0, percent))}%`);
    };
    const hideControls = () => {
      if (
        !isVideo ||
        media.paused ||
        seeking ||
        player.matches(":focus-within") ||
        !settingsPanel.hidden ||
        (contextMenu && !contextMenu.hidden)
      ) return;
      player.classList.add("custom-player-controls-hidden");
    };
    const showControls = () => {
      if (!isVideo) return;
      player.classList.remove("custom-player-controls-hidden");
      if (controlsTimer) window.clearTimeout(controlsTimer);
      if (!media.paused) controlsTimer = window.setTimeout(hideControls, 2600);
    };
    const syncFullscreen = () => {
      const active = fullscreenElement() === player;
      player.classList.toggle("custom-player-is-fullscreen", active);
      fullscreen.innerHTML = active ? playerIcon("fullscreenExit") : playerIcon("fullscreen");
      fullscreen.setAttribute("aria-label", active ? "Zamknij pełny ekran" : "Pełny ekran");
      fullscreen.title = active ? "Zamknij pełny ekran" : "Pełny ekran";
    };
    const syncPlay = () => {
      const paused = media.paused;
      const label = paused ? "Odtwórz" : "Pauza";
      const icon = paused ? playerIcon("play") : playerIcon("pause");
      [play, playSecondary].forEach((button) => {
        button.innerHTML = icon;
        button.setAttribute("aria-label", label);
        button.title = label;
      });
      player.classList.toggle("custom-player-playing", !paused);
      if (overlayIcon) overlayIcon.innerHTML = icon;
      showControls();
    };
    const syncMute = () => {
      const muted = media.muted || media.volume === 0;
      mute.innerHTML = muted ? playerIcon("volumeOff") : playerIcon("volume");
      mute.setAttribute("aria-label", muted ? "Włącz dźwięk" : "Wycisz");
      mute.title = muted ? "Włącz dźwięk" : "Wycisz";
      volume.value = String(media.muted ? 0 : media.volume);
      updateRangeFill(volume, Number(volume.value) * 100, "--volume-fill");
    };
    const persistSettings = () => writePlayerSettings({
      volume: media.volume,
      muted: media.muted,
      playbackRate: media.playbackRate,
      loop: media.loop,
      autoplayNext: settingAutoplayNext instanceof HTMLInputElement && settingAutoplayNext.checked,
      fitMode: player.classList.contains("custom-player-fit-cover") ? "cover" : "contain",
    });
    const syncSpeedButton = () => {
      const label = playbackRateLabel(media.playbackRate);
      settings.title = `Prędkość: ${label}`;
      if (speedValue) speedValue.textContent = label;
      if (speedSlider instanceof HTMLInputElement && document.activeElement !== speedSlider) {
        speedSlider.value = String(clampPlaybackRate(media.playbackRate));
      }
      if (speedSlider instanceof HTMLInputElement) {
        updateRangeFill(
          speedSlider,
          ((clampPlaybackRate(media.playbackRate) - 0.25) / 2.75) * 100,
          "--speed-fill"
        );
      }
    };
    const syncSettingsPanel = () => {
      syncSpeedButton();
      fitButtons.forEach((button) => {
        const activeFit = player.classList.contains("custom-player-fit-cover") ? "cover" : "contain";
        button.classList.toggle("custom-player-settings-active", button.dataset.fit === activeFit);
      });
      if (settingLoop instanceof HTMLInputElement) settingLoop.checked = media.loop;
      if (settingAutoplayNext instanceof HTMLInputElement) {
        settingAutoplayNext.disabled = !nextUrl;
      }
    };
    const setFitMode = (mode) => {
      player.classList.toggle("custom-player-fit-cover", mode === "cover");
      syncSettingsPanel();
      persistSettings();
    };
    const restorePosition = () => {
      const key = playerPositionKey(media);
      const saved = Number(readPlayerPositions()[key] || 0);
      if (key && saved > 3 && Number.isFinite(media.duration) && saved < media.duration - 3) {
        media.currentTime = saved;
      }
    };
    const syncTime = () => {
      const duration = Number.isFinite(media.duration) ? media.duration : 0;
      if (!seeking) progress.value = duration ? String((media.currentTime / duration) * 1000) : "0";
      updateRangeFill(progress, Number(progress.value) / 10, "--progress-fill");
      time.textContent = `${formatMediaTime(media.currentTime)} / ${formatMediaTime(duration)}`;
      if (overlayTime) overlayTime.textContent = time.textContent;
    };
    const seekBy = (seconds) => {
      const duration = Number.isFinite(media.duration) ? media.duration : 0;
      const target = Math.max(0, media.currentTime + seconds);
      media.currentTime = duration ? Math.min(duration, target) : target;
    };
    const updateSeekPreview = (clientX) => {
      if (!seekPreview || !seekPreviewTime) return;
      const duration = Number.isFinite(media.duration) ? media.duration : 0;
      if (!duration) return;
      const progressRect = progress.getBoundingClientRect();
      if (!progressRect.width) return;
      const playerRect = player.getBoundingClientRect();
      const ratio = Math.min(
        1,
        Math.max(0, (clientX - progressRect.left) / progressRect.width)
      );
      const previewX = progressRect.left + ratio * progressRect.width - playerRect.left;
      const previewTime = ratio * duration;
      if (seekPreviewImage && timelineThumbnails.length) {
        const frame = timelineThumbnails.reduce(
          (best, item) => (
            Math.abs(item.time - previewTime) < Math.abs(best.time - previewTime)
              ? item
              : best
          ),
          timelineThumbnails[0]
        );
        if (frame?.url && seekPreviewImage.src !== frame.url) seekPreviewImage.src = frame.url;
      }
      seekPreview.style.left = `${previewX}px`;
      seekPreviewTime.textContent = formatMediaTime(previewTime);
      seekPreview.classList.add("custom-player-seek-preview-visible");
    };
    const hideSeekPreview = () => {
      if (!seekPreview || seeking) return;
      seekPreview.classList.remove("custom-player-seek-preview-visible");
    };
    const changeVolumeBy = (delta) => {
      media.volume = Math.min(1, Math.max(0, media.volume + delta));
      media.muted = media.volume === 0;
      syncMute();
      persistSettings();
    };
    const handleKeyboardShortcut = (event) => {
      if (!isVideo || isEditableShortcutTarget(event.target)) return;
      const active = activeCustomPlayer === player;
      const fullscreenActive = fullscreenElement() === player;
      const focused = player.contains(document.activeElement);
      if (!active && !fullscreenActive && !focused) return;
      const key = event.key.toLowerCase();
      if (key === " " || key === "k") {
        event.preventDefault();
        play.click();
      } else if (key === "j") {
        event.preventDefault();
        seekBy(-10);
      } else if (key === "l") {
        event.preventDefault();
        seekBy(10);
      } else if (key === "arrowleft") {
        event.preventDefault();
        seekBy(-5);
      } else if (key === "arrowright") {
        event.preventDefault();
        seekBy(5);
      } else if (key === "arrowup") {
        event.preventDefault();
        changeVolumeBy(0.05);
      } else if (key === "arrowdown") {
        event.preventDefault();
        changeVolumeBy(-0.05);
      } else if (key === "m") {
        event.preventDefault();
        mute.click();
      } else if (key === "f") {
        event.preventDefault();
        fullscreen.click();
      } else {
        return;
      }
      showControls();
    };

    play.addEventListener("click", () => {
      if (media.paused) media.play().catch(() => {});
      else media.pause();
    });
    playSecondary.addEventListener("click", () => play.click());
    captions.addEventListener("click", () => {
      captions.classList.toggle("custom-player-button-active");
      captions.setAttribute(
        "aria-pressed",
        String(captions.classList.contains("custom-player-button-active"))
      );
    });
    settings.addEventListener("click", () => {
      settingsPanel.hidden = !settingsPanel.hidden;
      settings.classList.toggle("custom-player-button-active", !settingsPanel.hidden);
      syncSettingsPanel();
      showControls();
    });
    speedSlider?.addEventListener("input", () => {
      if (!(speedSlider instanceof HTMLInputElement)) return;
      speed.value = String(clampPlaybackRate(speedSlider.value));
      media.playbackRate = clampPlaybackRate(speed.value);
      syncSpeedButton();
    });
    speedSlider?.addEventListener("change", () => {
      persistSettings();
      syncSettingsPanel();
    });
    fitButtons.forEach((button) => {
      button.addEventListener("click", () => setFitMode(button.dataset.fit === "cover" ? "cover" : "contain"));
    });
    settingLoop?.addEventListener("change", () => {
      media.loop = settingLoop instanceof HTMLInputElement && settingLoop.checked;
      syncSettingsPanel();
      persistSettings();
    });
    settingAutoplayNext?.addEventListener("change", () => {
      persistSettings();
      syncSettingsPanel();
    });
    mute.addEventListener("click", () => {
      media.muted = !media.muted;
      syncMute();
      persistSettings();
    });
    volume.addEventListener("input", () => {
      media.volume = Number(volume.value);
      media.muted = media.volume === 0;
      syncMute();
      persistSettings();
    });
    speed.addEventListener("change", () => {
      media.playbackRate = clampPlaybackRate(speed.value);
      syncSpeedButton();
      persistSettings();
    });
    progress.addEventListener("input", () => {
      seeking = true;
      const duration = Number.isFinite(media.duration) ? media.duration : 0;
      updateRangeFill(progress, Number(progress.value) / 10, "--progress-fill");
      time.textContent = `${formatMediaTime((Number(progress.value) / 1000) * duration)} / ${formatMediaTime(duration)}`;
      showControls();
    });
    progress.addEventListener("change", () => {
      const duration = Number.isFinite(media.duration) ? media.duration : 0;
      media.currentTime = duration ? (Number(progress.value) / 1000) * duration : 0;
      seeking = false;
      syncTime();
      showControls();
    });
    progress.addEventListener("pointerenter", (event) => {
      updateSeekPreview(event.clientX);
      showControls();
    });
    progress.addEventListener("pointermove", (event) => {
      updateSeekPreview(event.clientX);
      showControls();
    });
    progress.addEventListener("pointerleave", hideSeekPreview);
    progress.addEventListener("pointerdown", (event) => {
      updateSeekPreview(event.clientX);
      showControls();
    });
    progress.addEventListener("pointerup", (event) => {
      updateSeekPreview(event.clientX);
      window.setTimeout(hideSeekPreview, 250);
    });
    fullscreen.addEventListener("click", async () => {
      try {
        if (fullscreenElement() === player) await exitFullscreen();
        else if (supportsFullscreen(player)) await requestFullscreen(player);
        else if (media.webkitEnterFullscreen) media.webkitEnterFullscreen();
      } catch (error) {
        console.error("Nie można uruchomić pełnego ekranu:", error);
      } finally {
        syncFullscreen();
        showControls();
      }
    });
    mini.addEventListener("click", () => {
      if (!(media instanceof HTMLVideoElement)) return;
      player.classList.toggle("custom-player-theater");
      document.body.classList.toggle(
        "custom-player-theater-active",
        player.classList.contains("custom-player-theater") && Boolean(player.closest(".preview-stage"))
      );
      mini.classList.toggle(
        "custom-player-button-active",
        player.classList.contains("custom-player-theater")
      );
      mini.setAttribute(
        "aria-pressed",
        String(player.classList.contains("custom-player-theater"))
      );
    });
    player.addEventListener("mousemove", showControls);
    player.addEventListener("mouseenter", () => {
      activeCustomPlayer = player;
      showControls();
    });
    player.addEventListener("touchstart", () => {
      activeCustomPlayer = player;
      showControls();
    }, { passive: true });
    player.addEventListener("focusin", () => {
      activeCustomPlayer = player;
      showControls();
    });
    player.addEventListener("keydown", showControls);
    controls.addEventListener("pointerdown", showControls);
    controls.addEventListener("pointerup", showControls);
    document.addEventListener("fullscreenchange", syncFullscreen);
    document.addEventListener("webkitfullscreenchange", syncFullscreen);
    document.addEventListener("keydown", handleKeyboardShortcut);
    document.addEventListener("pointerdown", (event) => {
      if (settingsPanel.hidden || player.contains(event.target)) return;
      settingsPanel.hidden = true;
      settings.classList.remove("custom-player-button-active");
    });
    media.addEventListener("click", () => {
      activeCustomPlayer = player;
      play.click();
      showControls();
    });
    media.addEventListener("play", syncPlay);
    media.addEventListener("pause", syncPlay);
    media.addEventListener("loadedmetadata", () => {
      restorePosition();
      syncTime();
    });
    media.addEventListener("timeupdate", () => {
      syncTime();
      writePlayerPosition(media);
    });
    media.addEventListener("volumechange", () => {
      syncMute();
      persistSettings();
    });
    media.addEventListener("ratechange", () => {
      const normalizedRate = clampPlaybackRate(media.playbackRate);
      if (normalizedRate !== media.playbackRate) {
        media.playbackRate = normalizedRate;
        return;
      }
      speed.value = String(media.playbackRate);
      syncSpeedButton();
      syncSettingsPanel();
      persistSettings();
    });
    media.addEventListener("ended", () => {
      writePlayerPosition(media);
      if (
        nextUrl &&
        settingAutoplayNext instanceof HTMLInputElement &&
        settingAutoplayNext.checked &&
        !media.loop
      ) {
        window.location.href = nextUrl;
      }
    });
    syncPlay();
    syncMute();
    syncTime();
    syncFullscreen();
    syncSpeedButton();
    syncSettingsPanel();
    if (media.hasAttribute("autoplay")) media.play().catch(() => {});
  };

  document.querySelectorAll("[data-custom-player]").forEach(enhanceCustomPlayer);

  document.querySelectorAll(".delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const filename = form.dataset.filename || "brak danych";
      const filesize = form.dataset.filesizeLabel || "brak danych";
      const message = `Czy na pewno usunąć pobrany plik?\n\nNazwa: ${filename}\nRozmiar: ${filesize}`;
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll(".history-delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const title = form.dataset.title || "brak danych";
      if (!window.confirm(`Czy na pewno usunąć wpis z historii?\n\nTytuł: ${title}`)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll(".download-form").forEach((form) => {
    const downloadProfile = form.querySelector('[name="download_profile"]');
    const downloadType = form.querySelector('[name="download_type"]');
    const formatId = form.querySelector('[name="format_id"]');
    if (!downloadType || !formatId) return;

    const syncFormatId = () => {
      const enabled = downloadType.value === "format";
      formatId.disabled = !enabled;
      formatId.required = enabled;
      if (!enabled) {
        formatId.value = "";
        formatId.classList.remove("is-invalid");
      }
    };

    const syncDownloadProfile = () => {
      const selected = downloadProfile?.selectedOptions?.[0];
      const profileDownloadType = selected?.dataset.downloadType || "";
      if (profileDownloadType) downloadType.value = profileDownloadType;
      syncFormatId();
    };

    downloadProfile?.addEventListener("change", syncDownloadProfile);
    downloadType.addEventListener("change", () => {
      if (downloadProfile && downloadProfile.value !== "manual") downloadProfile.value = "manual";
      syncFormatId();
    });
    formatId.addEventListener("input", () => {
      if (formatId.value.trim()) formatId.classList.remove("is-invalid");
    });
    form.addEventListener("submit", (event) => {
      const playlistInputs = Array.from(form.querySelectorAll(".playlist-entry-select"));
      if (playlistInputs.length && !playlistInputs.some((input) => input.checked)) {
        event.preventDefault();
        event.stopPropagation();
        playlistInputs[0].focus();
        return;
      }
      if (downloadType.value === "format" && !formatId.value.trim()) {
        event.preventDefault();
        event.stopPropagation();
        formatId.classList.add("is-invalid");
        formatId.focus();
      }
    });
    syncDownloadProfile();

    document.querySelectorAll(".format-download").forEach((button) => {
      button.addEventListener("click", () => {
        if (downloadProfile) downloadProfile.value = "manual";
        downloadType.value = "format";
        syncFormatId();
        formatId.value = button.dataset.formatId || "";
        formatId.classList.remove("is-invalid");
        form.requestSubmit();
      });
    });

    const playlistSelectAll = form.querySelector(".playlist-select-all");
    const syncPlaylistSelectAllLabel = () => {
      const inputs = Array.from(form.querySelectorAll(".playlist-entry-select"));
      if (playlistSelectAll && inputs.length) {
        playlistSelectAll.textContent = inputs.every((input) => input.checked)
          ? "Odznacz wszystkie"
          : "Zaznacz wszystkie";
      }
    };

    form.querySelectorAll(".playlist-entry-select").forEach((input) => {
      input.addEventListener("change", syncPlaylistSelectAllLabel);
    });
    playlistSelectAll?.addEventListener("click", () => {
      const inputs = Array.from(form.querySelectorAll(".playlist-entry-select"));
      const shouldCheck = inputs.some((input) => !input.checked);
      inputs.forEach((input) => {
        input.checked = shouldCheck;
      });
      syncPlaylistSelectAllLabel();
    });
    syncPlaylistSelectAllLabel();
  });

  const historyItems = Array.from(document.querySelectorAll(".history-item"));
  if (historyItems.length) {
    const typeFilter = document.getElementById("history-type-filter");
    const statusFilter = document.getElementById("history-status-filter");
    const sort = document.getElementById("history-sort");
    const previous = document.getElementById("history-prev");
    const next = document.getElementById("history-next");
    const pageLabel = document.getElementById("history-page");
    const empty = document.getElementById("history-filter-empty");
    const records = Array.from(
      new Map(historyItems.map((item) => [item.dataset.historyIndex, item])).values()
    );
    const pageSize = 10;
    let currentPage = 1;

    const addOptions = (select, values, labeler = (value) => value) => {
      values.forEach((value) => {
        const option = text("option", labeler(value));
        option.value = value;
        select?.append(option);
      });
    };

    addOptions(typeFilter, [...new Set(records.map((item) => item.dataset.historyType).filter(Boolean))].sort(), downloadTypeLabel);
    addOptions(statusFilter, [...new Set(records.map((item) => item.dataset.historyStatus).filter(Boolean))].sort());

    const renderHistory = () => {
      const filtered = records
        .filter((item) => !typeFilter?.value || item.dataset.historyType === typeFilter.value)
        .filter((item) => !statusFilter?.value || item.dataset.historyStatus === statusFilter.value)
        .sort((left, right) => {
          const order = left.dataset.historyDate.localeCompare(right.dataset.historyDate);
          return sort?.value === "oldest" ? order : -order;
        });
      const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
      currentPage = Math.min(currentPage, pageCount);
      const start = (currentPage - 1) * pageSize;
      const visibleIndexes = new Set(
        filtered.slice(start, start + pageSize).map((item) => item.dataset.historyIndex)
      );

      document.querySelectorAll(".history-items").forEach((container) => {
        const itemsByIndex = new Map(
          Array.from(container.querySelectorAll(".history-item")).map((item) => [
            item.dataset.historyIndex,
            item,
          ])
        );
        filtered.forEach((item) => {
          const target = itemsByIndex.get(item.dataset.historyIndex);
          if (target) container.append(target);
        });
      });
      historyItems.forEach((item) => {
        item.classList.toggle("d-none", !visibleIndexes.has(item.dataset.historyIndex));
      });
      document.querySelectorAll(".history-list").forEach((list) => {
        list.classList.toggle("d-none", filtered.length === 0);
      });
      empty?.classList.toggle("d-none", filtered.length > 0);
      document.getElementById("history-pagination")?.classList.toggle("d-none", filtered.length === 0);
      if (pageLabel) pageLabel.textContent = `Strona ${currentPage} z ${pageCount}`;
      if (previous) previous.disabled = currentPage <= 1;
      if (next) next.disabled = currentPage >= pageCount;
    };

    [typeFilter, statusFilter, sort].forEach((control) => {
      control?.addEventListener("change", () => {
        currentPage = 1;
        renderHistory();
      });
    });
    previous?.addEventListener("click", () => {
      currentPage -= 1;
      renderHistory();
    });
    next?.addEventListener("click", () => {
      currentPage += 1;
      renderHistory();
    });
    renderHistory();
  }

  const historyBulkForm = document.getElementById("history-bulk-form");
  if (historyBulkForm) {
    const selectedHistoryKeys = new Set();
    const historySelectionInputs = () => Array.from(historyBulkForm.querySelectorAll(".history-bulk-select"));
    const historyUniqueKeys = () => [...new Set(historySelectionInputs().map((input) => input.value).filter(Boolean))];
    const syncHistoryBulkControls = () => {
      historySelectionInputs().forEach((input) => {
        input.checked = selectedHistoryKeys.has(input.value);
      });
      const selectedCount = selectedHistoryKeys.size;
      const totalCount = historyUniqueKeys().length;
      const count = document.getElementById("history-selected-count");
      if (count) count.textContent = String(selectedCount);
      const button = document.getElementById("history-bulk-submit");
      if (button) button.disabled = selectedCount === 0;
      const selectAll = document.getElementById("history-bulk-select-all");
      if (selectAll) {
        selectAll.checked = totalCount > 0 && selectedCount === totalCount;
        selectAll.indeterminate = selectedCount > 0 && selectedCount < totalCount;
      }
    };

    historySelectionInputs().forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) selectedHistoryKeys.add(input.value);
        else selectedHistoryKeys.delete(input.value);
        syncHistoryBulkControls();
      });
    });
    document.getElementById("history-bulk-select-all")?.addEventListener("change", (event) => {
      if (event.target.checked) historyUniqueKeys().forEach((key) => selectedHistoryKeys.add(key));
      else selectedHistoryKeys.clear();
      syncHistoryBulkControls();
    });
    historyBulkForm.addEventListener("submit", (event) => {
      const selectedCount = selectedHistoryKeys.size;
      const action = historyBulkForm.querySelector(".history-bulk-action")?.value || "";
      const labels = {
        delete_entries: "usunąć zaznaczone wpisy z historii",
        delete_files: "usunąć pliki dla zaznaczonych wpisów",
        repeat: "ponownie pobrać zaznaczone pozycje",
      };
      if (!selectedCount || !window.confirm(`Czy na pewno ${labels[action] || "wykonać akcję"} (${selectedCount})?`)) {
        event.preventDefault();
      }
    });
    syncHistoryBulkControls();
  }

  const miniPlayerButtons = Array.from(document.querySelectorAll(".history-mini-player-toggle"));
  if (miniPlayerButtons.length) {
    const pausePanelMedia = (panel) => {
      panel.querySelectorAll("audio, video").forEach((media) => media.pause());
    };
    const setMiniPlayerOpen = (panel, open) => {
      panel.classList.toggle("d-none", !open);
      if (!open) pausePanelMedia(panel);
      miniPlayerButtons
        .filter((button) => button.dataset.target === panel.id)
        .forEach((button) => {
          button.setAttribute("aria-expanded", String(open));
          const label = open
            ? button.dataset.openLabel || "Zamknij"
            : button.dataset.closedLabel || "Odtwórz tutaj";
          if (button.classList.contains("history-icon-action")) {
            button.setAttribute("aria-label", label);
            button.setAttribute("title", label);
            const hiddenLabel = button.querySelector(".visually-hidden");
            if (hiddenLabel) hiddenLabel.textContent = label;
            return;
          }
          button.textContent = label;
        });
    };

    miniPlayerButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const panel = document.getElementById(button.dataset.target || "");
        if (!panel) return;
        const shouldOpen = panel.classList.contains("d-none");
        document.querySelectorAll(".history-mini-player").forEach((otherPanel) => {
          if (otherPanel !== panel) setMiniPlayerOpen(otherPanel, false);
        });
        setMiniPlayerOpen(panel, shouldOpen);
      });
    });
  }

  let activeJobStatuses = new Set();
  try {
    activeJobStatuses = new Set(JSON.parse(document.getElementById("active-job-statuses")?.textContent || "[]"));
  } catch (error) {
    console.error("Nie można odczytać listy aktywnych statusów:", error);
  }
  const isActiveJob = (job) => activeJobStatuses.has(job.status);
  const removableJobStatuses = new Set(["completed", "error", "stopped", "interrupted"]);
  const isRemovableJob = (job) => removableJobStatuses.has(job.status);
  const selectedJobIds = new Set();
  const openJobLogIds = new Set();
  const jobLogScrollTops = new Map();
  const jobFilterConfig = {
    all: {
      matches: () => true,
      emptyTitle: "Nie ma zadań",
      emptyCopy: "Wklej link na stronie startowej, a postęp pobierania pojawi się tutaj automatycznie.",
    },
    in_progress: {
      matches: isActiveJob,
      emptyTitle: "Nie ma zadań w toku",
      emptyCopy: "Wróć do pełnej kolejki, aby zobaczyć oczekujące, aktywne i zakończone pobrania.",
    },
    completed: {
      matches: (job) => job.status === "completed",
      emptyTitle: "Nie ma ukończonych zadań",
      emptyCopy: "Ukończone pobrania pojawią się tutaj po zakończeniu pracy kolejki.",
    },
    errors: {
      matches: (job) => job.status === "error",
      emptyTitle: "Nie ma nieudanych zadań",
      emptyCopy: "Filtr błędów jest pusty. Wróć do pełnej kolejki, aby zobaczyć aktywne i zakończone pobrania.",
    },
    stopped: {
      matches: (job) => job.status === "stopped",
      emptyTitle: "Nie ma zatrzymanych zadań",
      emptyCopy: "Zatrzymane pobrania pojawią się tutaj, gdy przerwiesz je ręcznie.",
    },
    interrupted: {
      matches: (job) => job.status === "interrupted",
      emptyTitle: "Nie ma przerwanych zadań",
      emptyCopy: "Przerwane zadania pojawią się tutaj po restarcie lub nieoczekiwanym zatrzymaniu pracy.",
    },
  };
  const initialJobsFilter = document.getElementById("jobs-filter-state")?.dataset.initialFilter || "all";
  let jobsFilter = jobFilterConfig[initialJobsFilter] ? initialJobsFilter : "all";

  const statusBadge = (job) => {
    const colors = {
      pending: "text-bg-secondary",
      downloading: "text-bg-primary",
      waiting: "text-bg-info",
      stopping: "text-bg-warning",
      completed: "text-bg-success",
      error: "text-bg-danger",
      stopped: "text-bg-warning",
      interrupted: "text-bg-warning",
    };
    return text("span", job.status_label, `badge ${colors[job.status] || "text-bg-secondary"}`);
  };

  const progressBar = (job) => {
    const wrapper = document.createElement("div");
    wrapper.className = "progress";
    wrapper.setAttribute("role", "progressbar");
    wrapper.setAttribute("aria-label", "Postęp pobierania");
    wrapper.setAttribute("aria-valuenow", String(job.progress || 0));
    wrapper.setAttribute("aria-valuemin", "0");
    wrapper.setAttribute("aria-valuemax", "100");
    const bar = document.createElement("div");
    bar.className = "progress-bar";
    bar.style.width = `${Math.min(100, Math.max(0, Number(job.progress) || 0))}%`;
    wrapper.append(bar);
    return wrapper;
  };

  const fileSize = (value) => {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = Number(value);
    if (!Number.isFinite(size) || size < 0) return null;
    for (const unit of units) {
      if (size < 1024 || unit === units[units.length - 1]) return `${size.toFixed(1)} ${unit}`;
      size /= 1024;
    }
    return null;
  };

  const jobSize = (job) => {
    const downloaded = fileSize(job.downloaded_bytes);
    const total = fileSize(job.total_bytes);
    if (downloaded && total && job.downloaded_bytes !== job.total_bytes) return `${downloaded} / ${total}`;
    return downloaded || total || "-";
  };

  const jobErrorHint = (job) => {
    const message = String(job.error_message || "").toLowerCase();
    if (message.includes("space") || message.includes("miejsca") || message.includes("disk")) {
      return "Wygląda na problem z miejscem na dysku. Zwolnij miejsce albo zmień katalog pobierania i ponów zadanie.";
    }
    if (message.includes("timed out") || message.includes("timeout") || message.includes("network") || message.includes("webpage")) {
      return "Wygląda na problem z połączeniem lub dostępnością strony. Sprawdź sieć, URL i ponów zadanie za chwilę.";
    }
    if (message.includes("ffmpeg") || message.includes("postprocessing") || message.includes("conversion")) {
      return "Pobranie doszło do etapu obróbki pliku. Sprawdź ffmpeg oraz wolne miejsce, potem ponów zadanie.";
    }
    if (message.includes("format") || message.includes("requested format")) {
      return "Wybrany format może nie być już dostępny. Wróć do analizy URL i wybierz inną jakość albo ponów pobieranie.";
    }
    return "Sprawdź komunikat błędu, URL i ustawienia formatu. Możesz ponowić zadanie pojedynczo albo użyć akcji dla wszystkich błędów.";
  };

  const jobErrorBlock = (job) => {
    if (job.status !== "error" && !job.error_message) return document.createDocumentFragment();
    const wrapper = document.createElement("div");
    wrapper.className = "job-error-box mt-2";
    const header = document.createElement("div");
    header.className = "d-flex flex-wrap gap-2 justify-content-between align-items-start";
    const message = text("strong", job.error_message || "Zadanie zakończyło się błędem.", "text-danger");
    const copyButton = text("button", "Kopiuj błąd", "btn btn-sm btn-soft job-error-copy");
    copyButton.type = "button";
    copyButton.dataset.copyText = job.error_message || "Zadanie zakończyło się błędem.";
    header.append(message, copyButton);
    wrapper.append(
      header,
      text("small", jobErrorHint(job), "text-body-secondary")
    );
    return wrapper;
  };

  const jobAutoRetryBlock = (job) => {
    const attempts = Number(job.auto_retry_attempts || 0);
    const maxAttempts = Number(job.auto_retry_max_attempts || 0);
    if (!attempts && !job.next_retry_at) return document.createDocumentFragment();
    let label = "";
    if (job.next_retry_at) {
      const retryDate = new Date(job.next_retry_at);
      const retryLabel = Number.isNaN(retryDate.getTime())
        ? job.next_retry_at
        : retryDate.toLocaleString();
      label = `Automatyczne ponowienie ${attempts}/${maxAttempts}: ${retryLabel}`;
    } else if (job.status === "error" && maxAttempts && attempts >= maxAttempts) {
      label = `Wykorzystano automatyczne próby: ${attempts}/${maxAttempts}`;
    } else if (attempts) {
      label = `Automatyczne próby: ${attempts}/${maxAttempts || attempts}`;
    }
    return label ? text("small", label, "job-auto-retry d-block text-body-secondary mt-1") : document.createDocumentFragment();
  };

  const captureJobLogScrollPositions = () => {
    document.querySelectorAll(".job-log[data-job-id] pre").forEach((pre) => {
      const jobId = pre.closest(".job-log")?.dataset.jobId;
      if (jobId && pre.offsetParent !== null) jobLogScrollTops.set(jobId, pre.scrollTop);
    });
  };

  const jobLogBlock = (job) => {
    const sourceLines = Array.isArray(job.recent_log_lines) ? job.recent_log_lines : job.log_lines;
    const lines = Array.isArray(sourceLines) ? sourceLines.filter(Boolean) : [];
    if (!lines.length) return document.createDocumentFragment();
    const details = document.createElement("details");
    details.className = "job-log mt-2";
    details.dataset.jobId = job.job_id;
    details.open = openJobLogIds.has(job.job_id);
    details.addEventListener("toggle", () => {
      if (details.open) openJobLogIds.add(job.job_id);
      else openJobLogIds.delete(job.job_id);
    });
    const summary = text("summary", `Log (${lines.length})`);
    const fullLogLink = text("a", "Pełny log", "btn btn-sm btn-soft job-full-log-link");
    fullLogLink.href = route(`/jobs/log/${encodeURIComponent(job.job_id)}`);
    fullLogLink.target = "_blank";
    fullLogLink.rel = "noreferrer";
    const pre = text("pre", lines.join("\n"));
    pre.addEventListener("scroll", () => {
      if (pre.offsetParent !== null) jobLogScrollTops.set(job.job_id, pre.scrollTop);
    });
    if (jobLogScrollTops.has(job.job_id)) {
      requestAnimationFrame(() => {
        pre.scrollTop = jobLogScrollTops.get(job.job_id) || 0;
      });
    }
    details.append(summary, fullLogLink, pre);
    return details;
  };

  const outputLink = (job) => {
    if (!job.output_file) return text("span", "-", "text-body-secondary");
    const link = text("a", "Pobierz", "btn btn-sm btn-soft");
    link.href = route(`/downloaded/${encodeURIComponent(job.output_file)}`);
    link.title = job.output_file;
    return link;
  };

  const jobPreviewPath = (job) => (
    job.output_file ? `/view/${encodeURIComponent(job.output_file)}` : ""
  );

  const jobTitle = (job) => {
    const heading = document.createElement("strong");
    const previewPath = jobPreviewPath(job);
    if (!previewPath) {
      heading.textContent = job.title;
      return heading;
    }
    const link = text("a", job.title, "job-title-link");
    link.href = route(previewPath);
    link.setAttribute("aria-label", `Otworz podglad: ${job.title}`);
    heading.append(link);
    return heading;
  };

  const jobThumbnail = (job, mobile = false) => {
    if (job.thumbnail_exists && job.thumbnail_filename) {
      const image = document.createElement("img");
      image.className = `job-thumbnail${mobile ? " job-thumbnail-mobile" : ""}`;
      image.src = route(`/thumbnails/${encodeURIComponent(job.thumbnail_filename)}`);
      image.alt = "";
      image.loading = "lazy";
      const previewPath = jobPreviewPath(job);
      if (previewPath) {
        const link = document.createElement("a");
        link.className = `job-thumbnail-link${mobile ? " d-block mb-3" : ""}`;
        link.href = route(previewPath);
        link.setAttribute("aria-label", `Otworz podglad: ${job.title}`);
        link.append(image);
        return link;
      }
      if (mobile) image.classList.add("mb-3");
      return image;
    }
    const placeholder = text("span", "-", `job-thumbnail-placeholder${mobile ? " job-thumbnail-mobile mb-3" : ""}`);
    placeholder.title = "Brak miniatury";
    placeholder.setAttribute("aria-label", "Brak miniatury");
    return placeholder;
  };

  const actionForm = (action, label, className, confirmation = "") => {
    const form = document.createElement("form");
    form.method = "post";
    form.action = action;
    if (confirmation) {
      form.addEventListener("submit", (event) => {
        if (!window.confirm(confirmation)) event.preventDefault();
      });
    }
    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "_csrf_token";
    token.value = csrfToken;
    const button = text("button", label, className);
    button.type = "submit";
    form.append(token, button);
    return form;
  };

  const repeatJobForm = (job) => {
    if (
      !job.url ||
      job.is_live ||
      job.status !== "completed" ||
      (job.download_type === "format" && !job.format_id)
    ) {
      return document.createDocumentFragment();
    }
    const form = actionForm(route("/download"), "Pobierz ponownie", "btn btn-sm btn-outline-primary");
    const fields = {
      url: job.url,
      title: job.title,
      download_type: job.download_type || "best",
      allow_duplicate: "1",
    };
    if (job.format_id) fields.format_id = job.format_id;
    if (job.duration) fields.duration = job.duration;
    Object.entries(fields).forEach(([name, value]) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = String(value);
      form.append(input);
    });
    return form;
  };

  const syncJobSelectionControls = () => {
    document.querySelectorAll(".job-select").forEach((checkbox) => {
      checkbox.checked = selectedJobIds.has(checkbox.value);
    });
    const inputs = document.getElementById("jobs-selected-inputs");
    inputs?.replaceChildren();
    selectedJobIds.forEach((jobId) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "job_ids";
      input.value = jobId;
      inputs?.append(input);
    });
    const count = document.getElementById("jobs-selected-count");
    if (count) count.textContent = String(selectedJobIds.size);
    const button = document.getElementById("jobs-delete-selected");
    if (button) button.disabled = selectedJobIds.size === 0;
  };

  const filteredJobs = (jobs) => {
    const config = jobFilterConfig[jobsFilter] || jobFilterConfig.all;
    return jobs.filter(config.matches);
  };

  const setJobsFilter = (filter, updateUrl = true) => {
    jobsFilter = jobFilterConfig[filter] ? filter : "all";
    document.querySelectorAll("[data-jobs-filter]").forEach((button) => {
      const active = button.dataset.jobsFilter === jobsFilter;
      const errorButton = button.dataset.jobsFilter === "errors";
      button.classList.toggle("btn-danger", active && errorButton);
      button.classList.toggle("btn-outline-danger", errorButton && !(active && errorButton));
      button.classList.toggle("btn-soft", !errorButton);
      button.setAttribute("aria-pressed", String(active));
    });
    if (updateUrl && document.getElementById("jobs-table-body")) {
      const url = new URL(window.location.href);
      if (jobsFilter !== "all") url.searchParams.set("filter", jobsFilter);
      else url.searchParams.delete("filter");
      window.history.replaceState({}, "", url);
    }
  };

  const updateJobsFilterEmptyState = () => {
    const config = jobFilterConfig[jobsFilter] || jobFilterConfig.all;
    const title = document.getElementById("jobs-filter-empty-title");
    const copy = document.getElementById("jobs-filter-empty-copy");
    if (title) title.textContent = config.emptyTitle;
    if (copy) copy.textContent = config.emptyCopy;
  };

  const updateJobsToolbar = (jobs) => {
    const jobsById = new Map(jobs.map((job) => [job.job_id, job]));
    selectedJobIds.forEach((jobId) => {
      const job = jobsById.get(jobId);
      if (!job || !isRemovableJob(job)) selectedJobIds.delete(jobId);
    });
    const visibleRemovableJobs = filteredJobs(jobs).filter(isRemovableJob);
    const failedJobs = jobs.filter((job) => job.status === "error");
    document.getElementById("jobs-toolbar")?.classList.toggle("d-none", jobs.length === 0);
    const totalCount = document.getElementById("jobs-total-count");
    if (totalCount) totalCount.textContent = String(jobs.length);
    document.querySelectorAll("[data-jobs-filter-count]").forEach((count) => {
      const filter = count.dataset.jobsFilterCount || "";
      const config = jobFilterConfig[filter];
      count.textContent = String(config ? jobs.filter(config.matches).length : 0);
    });
    const errorFilterCount = document.getElementById("jobs-error-filter-count");
    if (errorFilterCount) errorFilterCount.textContent = String(failedJobs.length);
    const failedCount = document.getElementById("jobs-failed-count");
    if (failedCount) failedCount.textContent = String(failedJobs.length);
    const retryFailed = document.getElementById("jobs-retry-failed");
    if (retryFailed) retryFailed.disabled = failedJobs.length === 0;
    const errorPanel = document.getElementById("jobs-error-panel");
    errorPanel?.classList.toggle("d-none", failedJobs.length === 0);
    const errorSummary = document.getElementById("jobs-error-summary");
    if (errorSummary) {
      errorSummary.textContent = failedJobs.length
        ? `Nieudane zadania: ${failedJobs.length}. Sprawdź krótki opis przy wpisie, popraw URL lub format i ponów zadanie.`
        : "Nieudane zadania zwykle oznaczają problem z URL, siecią, miejscem na dysku albo wybranym formatem.";
    }
    const selectAll = document.getElementById("jobs-select-all");
    if (selectAll) {
      const selectedCount = visibleRemovableJobs.filter((job) => selectedJobIds.has(job.job_id)).length;
      selectAll.disabled = visibleRemovableJobs.length === 0;
      selectAll.checked = visibleRemovableJobs.length > 0 && selectedCount === visibleRemovableJobs.length;
      selectAll.indeterminate = selectedCount > 0 && selectedCount < visibleRemovableJobs.length;
    }
    setJobsFilter(jobsFilter, false);
    updateJobsFilterEmptyState();
    syncJobSelectionControls();
  };

  const jobSelection = (job) => {
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "form-check-input job-select";
    checkbox.value = job.job_id;
    checkbox.checked = selectedJobIds.has(job.job_id);
    checkbox.disabled = !isRemovableJob(job);
    checkbox.setAttribute("aria-label", `Zaznacz zadanie ${job.title}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedJobIds.add(job.job_id);
      else selectedJobIds.delete(job.job_id);
      updateJobsToolbar(lastSuccessfulJobs || []);
    });
    return checkbox;
  };

  const jobActions = (job) => {
    const actions = document.createElement("span");
    actions.className = "d-flex flex-wrap gap-2";
    const detailsLink = text("a", "Szczegóły", "btn btn-sm btn-soft");
    detailsLink.href = route(`/jobs/${encodeURIComponent(job.job_id)}`);
    actions.append(detailsLink);
    if (job.is_live && ["pending", "downloading", "waiting"].includes(job.status)) {
      actions.append(actionForm(
        route(`/live/stop/${encodeURIComponent(job.job_id)}`),
        "Zatrzymaj",
        "btn btn-sm btn-outline-danger"
      ));
    } else if (!job.is_live && ["pending", "downloading"].includes(job.status)) {
      actions.append(actionForm(
        route(`/download/stop/${encodeURIComponent(job.job_id)}`),
        "Zatrzymaj",
        "btn btn-sm btn-outline-danger"
      ));
    } else if (!job.is_live && ["stopped", "interrupted"].includes(job.status)) {
      actions.append(actionForm(
        route(`/download/resume/${encodeURIComponent(job.job_id)}`),
        "Wznów",
        "btn btn-sm btn-outline-primary"
      ));
    }
    if (job.status === "error") {
      actions.append(actionForm(
        route(`/jobs/retry/${encodeURIComponent(job.job_id)}`),
        "Ponów",
        "btn btn-sm btn-outline-primary"
      ));
    }
    actions.append(repeatJobForm(job));
    if (isRemovableJob(job)) {
      actions.append(actionForm(
        route(`/jobs/delete/${encodeURIComponent(job.job_id)}`),
        "Usuń",
        "btn btn-sm btn-outline-danger",
        `Czy na pewno usunąć zadanie „${job.title}” z listy?`
      ));
    }
    return actions;
  };

  const renderTable = (jobs) => {
    const body = document.getElementById("jobs-table-body");
    if (!body) return;
    body.replaceChildren();
    jobs.forEach((job) => {
      const row = document.createElement("tr");
      const selectCell = document.createElement("td");
      selectCell.append(jobSelection(job));
      const thumbnailCell = document.createElement("td");
      thumbnailCell.append(jobThumbnail(job));
      const titleCell = document.createElement("td");
      titleCell.append(
        jobTitle(job),
        jobErrorBlock(job),
        jobAutoRetryBlock(job),
        text("small", job.warning_message || "", "job-error d-block text-warning"),
        jobLogBlock(job)
      );
      const typeCell = text("td", downloadTypeLabel(job.download_type));
      const statusCell = document.createElement("td");
      statusCell.append(statusBadge(job));
      const progressCell = document.createElement("td");
      progressCell.append(progressBar(job), text("small", `${job.progress || 0}%`, "text-body-secondary"));
      const sizeCell = text("td", jobSize(job));
      const speedCell = text("td", job.speed || "-");
      const etaCell = text("td", job.eta || "-");
      const outputCell = document.createElement("td");
      outputCell.append(outputLink(job));
      const actionCell = document.createElement("td");
      actionCell.append(jobActions(job));
      row.append(selectCell, thumbnailCell, titleCell, typeCell, statusCell, progressCell, sizeCell, speedCell, etaCell, outputCell, actionCell);
      body.append(row);
    });
  };

  const renderCards = (jobs) => {
    const list = document.getElementById("jobs-card-list");
    if (!list) return;
    list.replaceChildren();
    jobs.forEach((job) => {
      const card = document.createElement("article");
      card.className = "mobile-list-card p-3 mb-3";
      const heading = jobTitle(job);
      heading.classList.add("d-block");
      const meta = text("small", `${downloadTypeLabel(job.download_type)} | ${jobSize(job)} | ${job.speed || "-"} | ETA ${job.eta || "-"}`, "d-block text-body-secondary mb-2");
      const status = statusBadge(job);
      const progress = progressBar(job);
      progress.classList.add("my-2");
      const warning = text("small", job.warning_message || "", "d-block text-warning mb-2");
      const actions = document.createElement("div");
      actions.className = "d-flex flex-wrap gap-2 align-items-center";
      const selection = document.createElement("label");
      selection.className = "form-check d-flex gap-2 align-items-center mb-0";
      selection.append(jobSelection(job), text("span", "Zaznacz", "form-check-label"));
      actions.append(selection, outputLink(job), jobActions(job));
      card.append(jobThumbnail(job, true), heading, meta, status, progress, text("small", `${job.progress || 0}%`, "text-body-secondary"), jobErrorBlock(job), jobAutoRetryBlock(job), warning, jobLogBlock(job), actions);
      list.append(card);
    });
  };

  const updateActiveJobsBadge = (jobs) => {
    const badge = document.getElementById("active-jobs-badge");
    if (badge) badge.textContent = String(jobs.filter(isActiveJob).length);
  };

  const updateJobsView = (jobs) => {
    updateActiveJobsBadge(jobs);
    if (!document.getElementById("jobs-table-body")) return;
    captureJobLogScrollPositions();
    const visibleJobs = filteredJobs(jobs);
    document.getElementById("jobs-empty")?.classList.toggle("d-none", jobs.length > 0);
    document.getElementById("jobs-filter-empty")?.classList.toggle("d-none", jobs.length === 0 || visibleJobs.length > 0);
    updateJobsToolbar(jobs);
    renderTable(visibleJobs);
    renderCards(visibleJobs);
  };

  document.getElementById("jobs-select-all")?.addEventListener("change", (event) => {
    filteredJobs(lastSuccessfulJobs || []).filter(isRemovableJob).forEach((job) => {
      if (event.target.checked) selectedJobIds.add(job.job_id);
      else selectedJobIds.delete(job.job_id);
    });
    updateJobsToolbar(lastSuccessfulJobs || []);
  });

  document.querySelectorAll("[data-jobs-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      setJobsFilter(button.dataset.jobsFilter);
      updateJobsView(lastSuccessfulJobs || []);
    });
  });

  document.getElementById("jobs-show-errors")?.addEventListener("click", () => {
    setJobsFilter("errors");
    updateJobsView(lastSuccessfulJobs || []);
  });

  document.getElementById("jobs-select-errors")?.addEventListener("click", () => {
    (lastSuccessfulJobs || [])
      .filter((job) => job.status === "error")
      .forEach((job) => selectedJobIds.add(job.job_id));
    setJobsFilter("errors");
    updateJobsView(lastSuccessfulJobs || []);
  });

  document.getElementById("jobs-delete-selected-form")?.addEventListener("submit", (event) => {
    if (!selectedJobIds.size || !window.confirm(`Czy na pewno usunąć zaznaczone zadania (${selectedJobIds.size})?`)) {
      event.preventDefault();
    }
  });

  document.getElementById("jobs-clear-form")?.addEventListener("submit", (event) => {
    if (!window.confirm("Czy na pewno wyczyścić listę zakończonych zadań? Aktywne zadania pozostaną na liście.")) {
      event.preventDefault();
    }
  });

  document.getElementById("jobs-retry-failed-form")?.addEventListener("submit", (event) => {
    const failedCount = (lastSuccessfulJobs || []).filter((job) => job.status === "error").length;
    if (!failedCount || !window.confirm(`Ponowić wszystkie nieudane zadania (${failedCount})?`)) {
      event.preventDefault();
    }
  });

  const copyTextToClipboard = async (value) => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const fallback = document.createElement("textarea");
    fallback.value = value;
    fallback.setAttribute("readonly", "readonly");
    fallback.style.position = "fixed";
    fallback.style.opacity = "0";
    document.body.append(fallback);
    fallback.select();
    document.execCommand("copy");
    fallback.remove();
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".job-error-copy");
    if (!button) return;
    const originalLabel = button.textContent;
    try {
      await copyTextToClipboard(button.dataset.copyText || "");
      button.textContent = "Skopiowano";
    } catch (error) {
      console.error("Nie można skopiować błędu:", error);
      button.textContent = "Błąd kopiowania";
    } finally {
      window.setTimeout(() => {
        button.textContent = originalLabel;
      }, 1600);
    }
  });

  const setJobsRefreshError = (visible) => {
    document.getElementById("jobs-refresh-error")?.classList.toggle("d-none", !visible);
  };

  let lastSuccessfulJobs = null;
  let jobsRefreshInProgress = false;
  let knownJobStatuses = new Map();

  const notifyNewJobErrors = (jobs) => {
    const hadSnapshot = knownJobStatuses.size > 0;
    jobs.forEach((job) => {
      const previousStatus = knownJobStatuses.get(job.job_id);
      if (hadSnapshot && job.status === "error" && previousStatus !== "error") {
        showAppToast(`Zadanie zakończyło się błędem: ${job.title || job.job_id}`, {
          type: "danger",
          actionHref: route(`/jobs/log/${encodeURIComponent(job.job_id)}`),
          actionLabel: "Otwórz log",
        });
      }
    });
    knownJobStatuses = new Map(jobs.map((job) => [job.job_id, job.status]));
  };

  const refreshJobs = async () => {
    if (!document.getElementById("active-jobs-badge") || jobsRefreshInProgress) return;
    jobsRefreshInProgress = true;
    try {
      const response = await fetch(route("/api/jobs"), {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.jobs)) throw new Error("Niepoprawna odpowiedź API");
      notifyNewJobErrors(payload.jobs);
      lastSuccessfulJobs = payload.jobs;
      setJobsRefreshError(false);
      updateJobsView(lastSuccessfulJobs);
    } catch (error) {
      console.error("Nie można odświeżyć listy zadań:", error);
      setJobsRefreshError(true);
      if (lastSuccessfulJobs) updateJobsView(lastSuccessfulJobs);
    } finally {
      jobsRefreshInProgress = false;
    }
  };

  refreshJobs();
  if (document.getElementById("active-jobs-badge")) {
    window.setInterval(refreshJobs, jobsRefreshIntervalMs);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refreshJobs();
    });
    window.addEventListener("focus", refreshJobs);
  }
})();
