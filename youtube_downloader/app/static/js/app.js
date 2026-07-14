(() => {
  "use strict";

  const ingressPath = document.querySelector('meta[name="ingress-path"]')?.content || "";
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let translations = {};
  try {
    translations = JSON.parse(document.getElementById("ui-translations")?.textContent || "{}");
  } catch {
    translations = {};
  }
  const t = (key, values = {}) => {
    const template = translations[key] || key;
    return Object.entries(values).reduce(
      (textValue, [name, value]) => textValue.replaceAll(`{${name}}`, String(value ?? "")),
      template
    );
  };
  const themeStorageKey = "media-web-downloader-theme";
  const playerSettingsStorageKey = "media-web-downloader-player-settings";
  const playerPositionsStorageKey = "media-web-downloader-player-positions";
  const restorePathStorageKey = "media-web-downloader-restore-path";
  let intentionalNavigation = false;

  const route = (path) => `${ingressPath}${path}`;
  const encodeManagedPath = (value) => String(value || "")
    .split("/").map((part) => encodeURIComponent(part)).join("/");

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
    const nextTheme = theme === "dark" ? t("theme.light") : t("theme.dark");
    button.setAttribute("aria-label", t("theme.change_to", { theme: nextTheme }));
    button.setAttribute("title", t("theme.change_to", { theme: nextTheme }));
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
    close.setAttribute("aria-label", t("common.close"));
    close.title = t("common.close");
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

  const svgIcon = (name) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const paths = {
      chevron: ["m9 5 7 7-7 7"],
      close: ["M6 6l12 12M18 6 6 18"],
      more: ["M5 12h.01M12 12h.01M19 12h.01"],
      file: ["M6 3h8l4 4v14H6z", "M14 3v5h5"],
    };
    (paths[name] || paths.file).forEach((data) => {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", data);
      svg.append(path);
    });
    return svg;
  };

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);

  const downloadTypeLabel = (downloadType) => ({
    best: translations["download.best"] || "best",
    video: translations["download.video"] || "best",
    "video-1080": "1080p",
    "video-720": "720p",
    "video-360": "360p",
    audio: "audio MP3",
    format: translations["download.format"] || "format",
    live: "live",
  })[downloadType] || downloadType;

  const isValidMediaUrl = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol)
        && Boolean(url.hostname)
        && !url.username
        && !url.password
        && !url.port;
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
      bulkSummary.textContent = total > 1 ? t("js.url_selected", { selected, total }) : "";
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
        status.textContent = valid ? t("js.link", { number: index + 1 }) : t("js.invalid_url_item");
        const remove = document.createElement("button");
        remove.className = "bulk-url-remove";
        remove.type = "button";
        remove.setAttribute("aria-label", t("js.remove_link", { number: index + 1 }));
        remove.title = t("common.delete");
        remove.append(svgIcon("close"));
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
        copyInvalidUrls.textContent = t("js.copied");
        window.setTimeout(() => {
          copyInvalidUrls.textContent = t("index.copy_invalid");
        }, 1400);
      } catch (error) {
        console.error(t("js.copy_invalid_error"), error);
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
            ? t("js.paste_one")
            : invalidUrls.length
              ? t("js.invalid_urls", { urls: invalidUrls.join(", ") })
              : t("js.quick_one");
        }
        return;
      }
      if (input instanceof HTMLTextAreaElement) input.value = urls.join("\n");
      if (feedback) {
        feedback.textContent = t("index.invalid_url");
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
      if (label) label.textContent = t("js.analyzing");
      if (label && quickDownload) label.textContent = t("js.adding");
      const loading = form.querySelector(".analyze-loading");
      if (loading) {
        const loadingTitle = loading.querySelector("[data-loading-title]");
        const loadingCopy = loading.querySelector("[data-loading-copy]");
        const analysisDetails = loading.querySelector("[data-loading-analysis-details]");
        const analysisNote = loading.querySelector("[data-loading-analysis-note]");
        if (loadingTitle) loadingTitle.textContent = t(
          quickDownload ? "index.loading_download" : "index.loading_analyze"
        );
        if (loadingCopy) loadingCopy.textContent = t(
          quickDownload ? "index.loading_download_copy" : "index.loading_analyze_copy"
        );
        analysisDetails?.classList.toggle("d-none", quickDownload);
        analysisNote?.classList.toggle("d-none", quickDownload);
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
    const icon = document.createElement("span");
    icon.className = "custom-player-context-icon";
    icon.innerHTML = playerIcon(iconName);
    button.append(icon, text("span", label));
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
    0: t("js.network_empty"),
    1: t("js.network_idle"),
    2: t("js.network_loading"),
    3: t("js.network_no_source"),
  }[state] || "N/A");

  const mediaReadyStateLabel = (state) => ({
    0: t("common.no_data"),
    1: t("js.ready_metadata"),
    2: t("js.ready_current"),
    3: t("js.ready_future"),
    4: t("js.ready_enough"),
  }[state] || "N/A");

  const clampPlaybackRate = (value) => Math.min(3, Math.max(0.25, Number(value) || 1));

  const playbackRateLabel = (value) => {
    const rounded = Math.round(clampPlaybackRate(value) * 100) / 100;
    return `${String(rounded).replace(/\.?0+$/, "")}x`;
  };

  const formatPlayerBytes = (value) => {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes <= 0) return t("common.no_data");
    const units = ["B", "KB", "MB", "GB"];
    let size = bytes;
    for (const unit of units) {
      if (size < 1024 || unit === units[units.length - 1]) return `${size.toFixed(1)} ${unit}`;
      size /= 1024;
    }
    return t("common.no_data");
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
    return t("js.browser_api_unavailable");
  };

  const networkActivityLabel = (media, activity) => {
    const timing = mediaResourceTiming(media);
    const bytes = Number(timing?.transferSize || timing?.encodedBodySize || activity?.loadedBytes || 0);
    const eventAge = activity?.lastAt
      ? t("js.seconds_ago", { value: Math.max(0, ((Date.now() - activity.lastAt) / 1000)).toFixed(1) })
      : t("common.none");
    return [
      `${mediaNetworkStateLabel(media.networkState)} / ${mediaReadyStateLabel(media.readyState)}`,
      t("js.network_event", { event: activity?.lastEvent || "init", age: eventAge }),
      t("js.network_data", { value: formatPlayerBytes(bytes) }),
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

  const bufferRangesLabel = (media) => {
    const ranges = [];
    for (let index = 0; index < media.buffered.length; index += 1) {
      ranges.push(`${formatMediaTime(media.buffered.start(index))}-${formatMediaTime(media.buffered.end(index))}`);
    }
    return ranges.length ? ranges.join(", ") : t("common.none");
  };

  const estimatedBitrateLabel = (player, media) => {
    const bytes = Number(player.dataset.fileSize || 0);
    const duration = Number.isFinite(media.duration) ? media.duration : 0;
    if (bytes <= 0 || duration <= 0) return t("common.no_data");
    return `${((bytes * 8) / duration / 1000 / 1000).toFixed(2)} Mbps`;
  };

  const captionsStatsLabel = (player) => {
    const status = player.dataset.captionsStatus || t("js.captions_status_off");
    const label = player.dataset.captionsLabel || "";
    const source = player.dataset.captionsSourceLabel || "";
    return [status, label, source].filter(Boolean).join(" / ") || t("js.captions_status_off");
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
      ? t("js.debug_frames", {
        decoded: decodedFrames,
        dropped: Number.isFinite(droppedFrames) ? droppedFrames : "N/A",
      })
      : "N/A";
    const resolution = media.videoWidth && media.videoHeight
      ? `${media.videoWidth}x${media.videoHeight}`
      : "N/A";
    const source = media.querySelector("source");
    const mimeType = source?.type || player.dataset.mimeType || "";
    const duration = Number.isFinite(media.duration) ? formatMediaTime(media.duration) : "N/A";
    const current = Number.isFinite(media.currentTime) ? formatMediaTime(media.currentTime) : "N/A";
    const rows = [
      [t("js.debug_date"), new Date().toLocaleString()],
      [t("js.debug_video_id"), player.dataset.videoId || player.dataset.videoTitle || sourceLabelFromMedia(media)],
      [t("js.debug_viewport_frames"), `${viewport} / ${frames}`],
      [t("js.debug_file_resolution"), `${resolution} / ${estimatedBitrateLabel(player, media)}`],
      [t("js.debug_resolution"), `${resolution} / N/A`],
      [t("js.debug_volume"), `${media.muted ? t("js.debug_muted") : `${Math.round(media.volume * 100)}%`} / N/A`],
      [t("js.debug_format"), mimeType || "N/A"],
      [t("js.debug_color"), "N/A"],
      [t("js.debug_connection"), connectionSpeedLabel(media)],
      [t("js.debug_network"), networkActivityLabel(media, activity)],
      [t("js.debug_buffer"), bufferHealthLabel(media)],
      [t("js.debug_buffer_ranges"), bufferRangesLabel(media)],
      [t("js.debug_captions"), captionsStatsLabel(player)],
      [t("js.debug_file_path"), player.dataset.filePath || sourceLabelFromMedia(media)],
      [t("js.debug_details"), t("js.debug_detail_value", {
        current,
        duration,
        source: sourceLabelFromMedia(media),
      })],
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
    progress.setAttribute("aria-label", t("js.playback_progress"));

    const play = customPlayerButton(t("js.play"), playerIcon("play"), "custom-player-play");
    const playSecondary = customPlayerButton(
      t("js.play"),
      playerIcon("play"),
      "custom-player-play custom-player-play-secondary"
    );
    const mute = customPlayerButton(t("js.mute"), playerIcon("volume"), "custom-player-mute");
    const captions = customPlayerButton(
      t("js.captions"),
      playerIcon("captions"),
      "custom-player-captions"
    );
    captions.setAttribute("aria-pressed", "false");
    const captionsStatus = text("span", t("js.captions_status_off"), "custom-player-captions-status");
    const captionsGroup = document.createElement("span");
    captionsGroup.className = "custom-player-captions-group";
    captionsGroup.append(captions, captionsStatus);
    const settings = customPlayerButton(
      t("js.player_quality_speed"),
      `${playerIcon("settings")}<span class="custom-player-hd-badge">HD</span>`,
      "custom-player-settings"
    );
    const mini = customPlayerButton(
      t("js.theater_mode"),
      playerIcon("mini"),
      "custom-player-mini"
    );
    mini.setAttribute("aria-pressed", "false");
    const fullscreen = customPlayerButton(
      t("js.fullscreen"),
      playerIcon("fullscreen"),
      "custom-player-fullscreen"
    );
    const inThisVideo = document.createElement("button");
    inThisVideo.className = "custom-player-pill";
    inThisVideo.type = "button";
    inThisVideo.setAttribute("aria-label", t("preview.file_info"));
    inThisVideo.append(text("span", t("preview.file_info")), svgIcon("chevron"));
    const settingsPanel = document.createElement("div");
    settingsPanel.className = "custom-player-settings-panel";
    settingsPanel.hidden = true;
    settingsPanel.setAttribute("role", "menu");
    settingsPanel.setAttribute("aria-label", t("js.player_settings"));
    const settingsHeading = text("div", t("js.settings"), "custom-player-settings-heading");
    const qualityRow = document.createElement("div");
    qualityRow.className = "custom-player-settings-row";
    qualityRow.append(
      text("span", t("js.quality")),
      text("strong", player.dataset.qualityLabel || t("js.original_quality"))
    );
    const speedGroup = document.createElement("div");
    speedGroup.className = "custom-player-settings-group";
    speedGroup.dataset.settingGroup = "speed";
    const speedRow = document.createElement("div");
    speedRow.className = "custom-player-settings-row";
    const speedSettingValue = text("strong", playbackRateLabel(media.playbackRate));
    speedSettingValue.dataset.speedValue = "";
    speedRow.append(text("span", t("js.speed")), speedSettingValue);
    const speedControl = document.createElement("div");
    speedControl.className = "custom-player-speed-control";
    const speedSettingSlider = document.createElement("input");
    speedSettingSlider.className = "custom-player-range custom-player-speed-slider";
    speedSettingSlider.type = "range";
    speedSettingSlider.min = "0.25";
    speedSettingSlider.max = "3";
    speedSettingSlider.step = "0.05";
    speedSettingSlider.value = String(media.playbackRate);
    speedSettingSlider.dataset.speedSlider = "";
    speedSettingSlider.setAttribute("aria-label", t("js.speed"));
    const speedScale = document.createElement("div");
    speedScale.className = "custom-player-speed-scale";
    speedScale.setAttribute("aria-hidden", "true");
    speedScale.append(text("span", "0.25x"), text("span", "1x"), text("span", "3x"));
    speedControl.append(speedSettingSlider, speedScale);
    speedGroup.append(speedRow, speedControl);
    const settingToggle = (label, dataName) => {
      const wrapper = document.createElement("label");
      wrapper.className = "custom-player-settings-toggle";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset[dataName] = "";
      wrapper.append(text("span", label), input);
      return wrapper;
    };
    const fitGroup = document.createElement("div");
    fitGroup.className = "custom-player-settings-group";
    fitGroup.dataset.settingGroup = "fit";
    const fitOptions = document.createElement("div");
    fitOptions.className = "custom-player-settings-options";
    [["contain", "js.fit_contain"], ["cover", "js.fit_cover"]].forEach(([mode, key]) => {
      const button = text("button", t(key));
      button.type = "button";
      button.dataset.fit = mode;
      fitOptions.append(button);
    });
    fitGroup.append(text("span", t("js.fit")), fitOptions);
    const captionsSettingsGroupNode = document.createElement("div");
    captionsSettingsGroupNode.className = "custom-player-settings-group";
    captionsSettingsGroupNode.dataset.settingGroup = "captions";
    const captionsOptions = document.createElement("div");
    captionsOptions.className = "custom-player-settings-options";
    [["pl", "js.captions_polish"], ["en", "js.captions_english"],
      ["auto", "js.captions_auto"], ["off", "js.captions_off"]].forEach(([mode, key]) => {
      const button = text("button", t(key));
      button.type = "button";
      button.dataset.captionsMode = mode;
      captionsOptions.append(button);
    });
    const captionsSettingStatus = text(
      "small", t("js.captions_status_off"), "custom-player-setting-status"
    );
    captionsSettingStatus.dataset.captionsPanelStatus = "";
    captionsSettingsGroupNode.append(
      text("span", t("js.captions")), captionsOptions, captionsSettingStatus
    );
    settingsPanel.append(
      settingsHeading,
      qualityRow,
      speedGroup,
      settingToggle(t("js.loop"), "settingLoop"),
      settingToggle(t("js.autoplay_next"), "settingAutoplayNext"),
      fitGroup,
      captionsSettingsGroupNode
    );
    const time = text("span", "0:00 / 0:00", "custom-player-time");
    const speed = document.createElement("input");
    speed.className = "custom-player-speed";
    speed.type = "range";
    speed.min = "0.25";
    speed.max = "3";
    speed.step = "0.05";
    speed.value = String(media.playbackRate);
    speed.setAttribute("aria-label", t("js.speed"));
    const volume = document.createElement("input");
    volume.className = "custom-player-range custom-player-volume";
    volume.type = "range";
    volume.min = "0";
    volume.max = "1";
    volume.step = "0.01";
    volume.value = String(media.volume || 1);
    volume.setAttribute("aria-label", t("js.volume"));

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
    rightControls.append(playSecondary, captionsGroup, settings, mini, fullscreen);
    mainRow.append(leftControls, rightControls);
    controls.append(progress, mainRow, speed);
    player.append(controls);
    player.append(settingsPanel);
    if (!supportsFullscreen(player) && !media.webkitEnterFullscreen) fullscreen.hidden = true;
    const nextUrl = player.dataset.nextUrl || "";
    const captionsUrl = player.dataset.captionsUrl || "";
    const settingLoop = settingsPanel.querySelector("[data-setting-loop]");
    const settingAutoplayNext = settingsPanel.querySelector("[data-setting-autoplay-next]");
    const speedSlider = settingsPanel.querySelector("[data-speed-slider]");
    const speedValue = settingsPanel.querySelector("[data-speed-value]");
    const fitButtons = Array.from(settingsPanel.querySelectorAll("[data-fit]"));
    const captionsModeButtons = Array.from(settingsPanel.querySelectorAll("[data-captions-mode]"));
    const captionsPanelStatus = settingsPanel.querySelector("[data-captions-panel-status]");
    const captionsSettingsGroup = settingsPanel.querySelector("[data-setting-group='captions']");
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
      overlay.setAttribute("aria-label", t("js.play_pause"));
      overlay.title = t("js.play_pause");
      overlayIcon = text("span", "", "custom-player-overlay-icon");
      overlayIcon.innerHTML = playerIcon("play");
      overlayTime = text("span", "0:00 / 0:00", "custom-player-overlay-time");
      overlay.append(overlayIcon, overlayTime);
      overlay.addEventListener("click", () => play.click());
      player.append(overlay);
    }

    let contextMenu = null;
    let statsOverlay = null;
    let statsContent = null;
    let statsTimer = null;
    let captionsTrack = null;
    let captionsLoadedMode = "";
    let captionsLoading = false;
    let captionsMode = "off";
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
      contextMenu.setAttribute("aria-label", t("js.context_menu"));

      statsOverlay = document.createElement("section");
      statsOverlay.className = "custom-player-stats";
      statsOverlay.hidden = true;
      statsOverlay.setAttribute("aria-label", t("js.stats"));
      const statsHeader = document.createElement("div");
      statsHeader.className = "custom-player-stats-header";
      statsHeader.append(text("strong", t("js.stats")));
      const statsClose = document.createElement("button");
      statsClose.className = "custom-player-stats-close";
      statsClose.type = "button";
      statsClose.append(svgIcon("close"));
      statsClose.setAttribute("aria-label", t("js.close_stats"));
      statsClose.title = t("js.close_stats");
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
          console.error(t("js.copy_failed"), error);
          showPlayerCopyFeedback(t("js.copy_failed"));
          showAppToast(t("js.copy_failed"), { type: "danger" });
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
          console.error(t("js.pip_error"), error);
          mini.click();
        }
      };

      loopContextItem = createPlayerContextMenuItem(t("js.loop_playback"), "loop", () => {
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
        createPlayerContextMenuItem(t("js.mini_player"), "mini", () => {
          hideContextMenu();
          togglePictureInPicture();
        }),
        createPlayerContextMenuItem(t("js.copy_video_url"), "copy", () => {
          hideContextMenu();
          copyPlayerValue(sourceUrlForCopy(), t("js.copied_video_url"));
        }),
        createPlayerContextMenuItem(t("js.copy_time_url"), "linkTime", () => {
          hideContextMenu();
          copyPlayerValue(currentTimeUrl(), t("js.copied_time_url"));
        }),
        createPlayerContextMenuItem(t("js.copy_embed"), "embed", () => {
          hideContextMenu();
          copyPlayerValue(embedCode(), t("js.copied_embed"));
        }),
        createPlayerContextMenuItem(t("js.copy_debug"), "debug", () => {
          hideContextMenu();
          copyPlayerValue(formatVideoDebugStats(player, media, networkActivity), t("js.copied_debug"));
        }),
        createPlayerContextMenuItem(t("js.troubleshoot_playback"), "flag", () => {
          hideContextMenu();
          showAppToast(t("js.open_diagnostics"), {
            type: "info",
            actionHref: route("/diagnostics"),
            actionLabel: t("nav.diagnostics"),
          });
        }),
        createPlayerContextMenuItem(t("js.stats"), "stats", () => {
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
      fullscreen.setAttribute("aria-label", active ? t("js.exit_fullscreen") : t("js.fullscreen"));
      fullscreen.title = active ? t("js.exit_fullscreen") : t("js.fullscreen");
    };
    const syncPlay = () => {
      const paused = media.paused;
      const label = paused ? t("js.play") : t("js.pause");
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
    const syncCaptionsButton = (active) => {
      captions.classList.toggle("custom-player-button-active", active);
      captions.setAttribute("aria-pressed", String(active));
    };
    const setCaptionsStatus = (key, payload = {}) => {
      const label = payload.label || t(key);
      captionsStatus.textContent = label;
      if (captionsPanelStatus) captionsPanelStatus.textContent = label;
      player.dataset.captionsStatus = label;
      if (payload.captionLabel !== undefined) player.dataset.captionsLabel = payload.captionLabel || "";
      if (payload.sourceLabel !== undefined) player.dataset.captionsSourceLabel = payload.sourceLabel || "";
      captions.title = `${t("js.captions")}: ${label}`;
    };
    const syncCaptionsModeButtons = () => {
      captionsModeButtons.forEach((button) => {
        button.classList.toggle("custom-player-settings-active", button.dataset.captionsMode === captionsMode);
      });
    };
    const showTextTracks = (active) => {
      Array.from(media.textTracks || []).forEach((track) => {
        track.mode = active ? "showing" : "disabled";
      });
      syncCaptionsButton(active);
      if (!active) {
        captionsMode = "off";
        setCaptionsStatus("js.captions_status_off", { captionLabel: "", sourceLabel: "" });
        syncCaptionsModeButtons();
      }
    };
    const removeDownloadedCaptions = () => {
      if (captionsTrack) captionsTrack.remove();
      captionsTrack = null;
      captionsLoadedMode = "";
      Array.from(media.querySelectorAll("track[data-downloaded-captions='true']")).forEach((track) => track.remove());
    };
    const attachDownloadedCaptions = (payload, mode) => {
      removeDownloadedCaptions();
      const track = document.createElement("track");
      track.kind = "subtitles";
      track.label = payload.label || t("js.captions");
      track.srclang = String(payload.language || payload.label || mode || "pl").toLowerCase();
      track.src = payload.url;
      track.default = true;
      track.dataset.downloadedCaptions = "true";
      track.dataset.captionLabel = payload.label || "";
      track.dataset.sourceLabel = payload.source_label || "";
      media.append(track);
      captionsTrack = track;
      captionsLoadedMode = mode;
      captionsMode = mode;
      setCaptionsStatus("js.captions_status_on", {
        captionLabel: payload.label || "",
        sourceLabel: payload.source_label || "",
      });
      syncCaptionsModeButtons();
      window.setTimeout(() => showTextTracks(true), 0);
    };
    const loadCaptions = async (mode = "pl") => {
      if (mode === "off") {
        showTextTracks(false);
        return;
      }
      if (!captionsUrl || captionsLoading) return;
      if (captionsLoadedMode === mode && captionsTrack) {
        captionsMode = mode;
        setCaptionsStatus("js.captions_status_on", {
          captionLabel: captionsTrack.dataset.captionLabel || captionsTrack.label || "",
          sourceLabel: captionsTrack.dataset.sourceLabel || "",
        });
        syncCaptionsModeButtons();
        showTextTracks(true);
        return;
      }
      captionsLoading = true;
      captions.disabled = true;
      setCaptionsStatus("js.captions_status_loading");
      try {
        const formData = new FormData();
        formData.append("_csrf_token", csrfToken);
        formData.append("mode", mode);
        const response = await fetch(captionsUrl, {
          method: "POST",
          body: formData,
          cache: "no-store",
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false || !payload.url) {
          const error = new Error(payload.message || t("js.captions_unavailable"));
          error.noCaptions = payload.reason === "unavailable";
          throw error;
        }
        attachDownloadedCaptions(payload, mode);
        showAppToast(t("js.captions_loaded"), { type: "success" });
      } catch (error) {
        showTextTracks(false);
        setCaptionsStatus(error?.noCaptions ? "js.captions_status_missing" : "js.captions_status_error");
        showAppToast(error?.message || t("js.captions_error"), { type: "warning" });
      } finally {
        captionsLoading = false;
        captions.disabled = false;
      }
    };
    setCaptionsStatus("js.captions_status_off", { captionLabel: "", sourceLabel: "" });
    syncCaptionsModeButtons();
    const syncMute = () => {
      const muted = media.muted || media.volume === 0;
      mute.innerHTML = muted ? playerIcon("volumeOff") : playerIcon("volume");
      mute.setAttribute("aria-label", muted ? t("js.unmute") : t("js.mute"));
      mute.title = muted ? t("js.unmute") : t("js.mute");
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
      settings.title = t("js.speed_value", { value: label });
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
      syncCaptionsModeButtons();
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
    if (!isVideo || !captionsUrl) {
      captions.hidden = true;
      captionsStatus.hidden = true;
      captionsSettingsGroup?.setAttribute("hidden", "hidden");
    }
    captions.addEventListener("click", () => {
      if (!captionsTrack) {
        loadCaptions("pl");
        return;
      }
      const active = !captions.classList.contains("custom-player-button-active");
      if (active && captionsTrack) {
        captionsMode = captionsLoadedMode || "pl";
        setCaptionsStatus("js.captions_status_on", {
          captionLabel: captionsTrack.dataset.captionLabel || captionsTrack.label || "",
          sourceLabel: captionsTrack.dataset.sourceLabel || "",
        });
        syncCaptionsModeButtons();
      }
      showTextTracks(active);
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
    captionsModeButtons.forEach((button) => {
      button.addEventListener("click", () => loadCaptions(button.dataset.captionsMode || "off"));
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
        console.error(t("js.fullscreen_error"), error);
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
      const filename = form.dataset.filename || t("common.no_data");
      const filesize = form.dataset.filesizeLabel || t("common.no_data");
      const message = t("js.delete_file_confirm", { filename, size: filesize });
      if (!window.confirm(message)) {
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
    const playlistStart = form.querySelector('[name="playlist_start"]');
    const playlistEnd = form.querySelector('[name="playlist_end"]');
    const playlistLimit = form.querySelector('[name="playlist_limit"]');
    const syncPlaylistSelectAllLabel = () => {
      const inputs = Array.from(form.querySelectorAll(".playlist-entry-select"));
      if (playlistSelectAll && inputs.length) {
        playlistSelectAll.textContent = inputs.every((input) => input.checked)
          ? t("result.unselect_all")
          : t("result.select_all");
      }
    };
    const playlistNumber = (input) => {
      const value = Number.parseInt(input?.value || "", 10);
      return Number.isFinite(value) && value > 0 ? value : null;
    };
    const applyPlaylistRange = () => {
      const inputs = Array.from(form.querySelectorAll(".playlist-entry-select"));
      const start = playlistNumber(playlistStart);
      const end = playlistNumber(playlistEnd);
      const limit = playlistNumber(playlistLimit);
      let selected = 0;
      inputs.forEach((input) => {
        const index = Number.parseInt(input.value || "", 10) + 1;
        const inRange = (!start || index >= start) && (!end || index <= end);
        const belowLimit = !limit || selected < limit;
        input.checked = inRange && belowLimit;
        if (input.checked) selected += 1;
      });
      syncPlaylistSelectAllLabel();
    };

    form.querySelectorAll(".playlist-entry-select").forEach((input) => {
      input.addEventListener("change", syncPlaylistSelectAllLabel);
    });
    [playlistStart, playlistEnd, playlistLimit].forEach((input) => {
      input?.addEventListener("input", applyPlaylistRange);
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

  let activeJobStatuses = new Set();
  try {
    activeJobStatuses = new Set(JSON.parse(document.getElementById("active-job-statuses")?.textContent || "[]"));
  } catch (error) {
    console.error(t("js.bad_api"), error);
  }

  const libraryList = document.getElementById("jobs-list");
  const activeDownloadsList = document.getElementById("active-downloads-list");
  const recentDownloadsList = document.getElementById("recent-downloads-list");
  const libraryPageVisible = Boolean(libraryList);
  const selectedJobIds = new Set();
  const itemReferences = new WeakMap();
  let lastSuccessfulJobs = [];
  let jobsRefreshInProgress = false;
  let jobsRefreshTimer = 0;
  let knownJobStatuses = new Map();
  let jobsFilter = document.getElementById("jobs-filter-state")?.dataset.initialFilter || "all";
  let jobsQuery = "";
  let jobsSort = "newest";

  const activeFilterStatuses = new Set(["downloading", "stopping"]);
  const queuedFilterStatuses = new Set(["pending", "waiting"]);
  const isActiveJob = (job) => activeJobStatuses.has(job.status);
  const isRemovableJob = (job) => job.can_delete === true;

  const setNodeText = (node, value) => {
    if (!node) return;
    const next = String(value ?? "");
    if (node.textContent !== next) node.textContent = next;
  };

  const setNodeAttribute = (node, name, value) => {
    if (!node) return;
    const next = String(value ?? "");
    if (node.getAttribute(name) !== next) node.setAttribute(name, next);
  };

  const sourceLabel = (job) => {
    const metadata = job.metadata && typeof job.metadata === "object" ? job.metadata : {};
    const source = job.extractor_key || job.platform || metadata.extractor_key
      || metadata.extractor || metadata.platform || job.source_id;
    if (source) return String(source);
    try {
      return new URL(job.url).hostname.replace(/^www\./, "");
    } catch {
      return t("js.source_unknown");
    }
  };

  const normalizeJob = (raw) => {
    const job = { ...raw };
    job.job_id = String(raw?.job_id || "");
    job.title = String(raw?.title || job.job_id);
    job.url = String(raw?.url || "");
    job.status = String(raw?.status || "");
    job.status_label = String(raw?.status_label || job.status);
    job.download_type = String(raw?.download_type || "best");
    job.output_file = String(raw?.output_file || "");
    job.source_label = sourceLabel(job);
    job.progress = Math.min(100, Math.max(0, Number(raw?.progress) || 0));
    job.date_value = String(raw?.finished_at || raw?.created_at || "");
    job.search_value = [job.title, job.url, job.source_label, job.source_id, job.output_file]
      .join(" ").toLocaleLowerCase();
    return job;
  };

  const fileSize = (value) => {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = Number(value);
    if (!Number.isFinite(size) || size < 0) return "";
    for (const unit of units) {
      if (size < 1024 || unit === units[units.length - 1]) return size.toFixed(1) + " " + unit;
      size /= 1024;
    }
    return "";
  };

  const durationLabel = (value) => {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return "";
    const whole = Math.floor(seconds);
    return [Math.floor(whole / 3600), Math.floor((whole % 3600) / 60), whole % 60]
      .map((part) => String(part).padStart(2, "0")).join(":");
  };

  const dateLabel = (value) => {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value).replace("T", " ").slice(0, 19) : date.toLocaleString();
  };

  const jobSize = (job) => {
    const downloaded = fileSize(job.downloaded_bytes);
    const total = fileSize(job.total_bytes);
    if (downloaded && total && Number(job.downloaded_bytes) !== Number(job.total_bytes)) return downloaded + " / " + total;
    return downloaded || total || t("common.no_data");
  };

  const liveInfo = (job) => {
    if (!job.is_live) return "";
    if (job.live_status_message) return String(job.live_status_message);
    const elapsed = durationLabel(job.live_elapsed_seconds);
    return elapsed ? t("js.live_elapsed", { time: elapsed }) : "";
  };

  const statusClass = (status) => ({
    downloading: "library-status-active", stopping: "library-status-stopped",
    pending: "library-status-queued", waiting: "library-status-queued",
    completed: "library-status-completed", error: "library-status-error",
    stopped: "library-status-stopped", interrupted: "library-status-stopped",
  }[status] || "library-status-neutral");

  const actionForm = (action, label, className, confirmation = "") => {
    const form = document.createElement("form");
    form.method = "post";
    form.action = action;
    if (confirmation) form.addEventListener("submit", (event) => {
      if (!window.confirm(confirmation)) event.preventDefault();
    });
    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "_csrf_token";
    token.value = csrfToken;
    const button = text("button", label, className);
    button.type = "submit";
    form.append(token, button);
    return form;
  };

  const repeatJobForm = (job, className = "btn btn-sm btn-soft") => {
    const form = actionForm(route("/download"), t("common.download_again"), className);
    const fields = { url: job.url, title: job.title, download_type: job.download_type || "best",
      storage_name: job.storage_name || "local", allow_duplicate: "1" };
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

  const linkAction = (href, label, className = "btn btn-sm btn-soft") => {
    const link = text("a", label, className);
    link.href = href;
    return link;
  };

  const deleteFileForm = (job) => {
    const form = actionForm(route("/delete/" + encodeManagedPath(job.output_file)), t("common.delete_file"),
      "library-menu-action library-menu-danger",
      t("js.delete_file_confirm", { filename: job.output_file, size: jobSize(job) }));
    const returnTo = document.createElement("input");
    returnTo.type = "hidden";
    returnTo.name = "return_to";
    returnTo.value = "jobs";
    form.append(returnTo);
    return form;
  };

  const primaryAction = (job) => {
    if (job.can_stop) return actionForm(
      route("/" + (job.is_live ? "live" : "download") + "/stop/" + encodeURIComponent(job.job_id)),
      t("job.stop"), "btn btn-sm btn-outline-danger");
    if (job.can_resume) return actionForm(route("/download/resume/" + encodeURIComponent(job.job_id)),
      t("job.resume"), "btn btn-sm btn-primary");
    if (job.can_retry) return actionForm(route("/jobs/retry/" + encodeURIComponent(job.job_id)),
      t("common.retry"), "btn btn-sm btn-primary");
    if (job.status === "completed" && job.file_exists && job.output_file) {
      return linkAction(route("/view/" + encodeManagedPath(job.output_file)), t("jobs.open"), "btn btn-sm btn-primary");
    }
    if (job.status === "completed" && job.can_repeat) return repeatJobForm(job, "btn btn-sm btn-primary");
    return linkAction(route("/jobs/" + encodeURIComponent(job.job_id)), t("js.primary_details"));
  };

  const menuActions = (job) => {
    const fragment = document.createDocumentFragment();
    fragment.append(
      linkAction(route("/jobs/" + encodeURIComponent(job.job_id)), t("common.details"), "library-menu-action"),
      linkAction(route("/jobs/log/" + encodeURIComponent(job.job_id)), t("common.full_log"), "library-menu-action")
    );
    if (job.can_repeat) fragment.append(repeatJobForm(job, "library-menu-action"));
    if (job.file_exists && job.output_file) {
      fragment.append(linkAction(route("/view/" + encodeManagedPath(job.output_file)), t("common.open_file"), "library-menu-action"));
      fragment.append(deleteFileForm(job));
    }
    if (job.can_delete) fragment.append(actionForm(route("/jobs/delete/" + encodeURIComponent(job.job_id)),
      t("common.delete_entry"), "library-menu-action library-menu-danger",
      t("js.delete_entry_confirm", { title: job.title })));
    return fragment;
  };

  const createMetric = (label) => {
    const wrapper = document.createElement("span");
    wrapper.className = "library-metric";
    wrapper.append(text("small", label), text("strong", ""));
    return { wrapper, value: wrapper.lastElementChild };
  };

  const createLibraryItem = (job, options = {}) => {
    const item = document.createElement("article");
    item.className = "library-item";
    item.dataset.jobId = job.job_id;
    const selectWrap = document.createElement("label");
    selectWrap.className = "library-select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "form-check-input job-select";
    checkbox.value = job.job_id;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedJobIds.add(checkbox.value);
      else selectedJobIds.delete(checkbox.value);
      updateSelectionControls();
    });
    selectWrap.append(checkbox);

    const thumbnail = document.createElement("a");
    thumbnail.className = "library-thumbnail";
    const image = document.createElement("img");
    image.alt = "";
    image.loading = "lazy";
    const placeholder = svgIcon("file");
    placeholder.classList.add("library-thumbnail-placeholder");
    thumbnail.append(image, placeholder);

    const main = document.createElement("div");
    main.className = "library-main";
    const titleLink = text("a", "", "library-title");
    const meta = document.createElement("div");
    meta.className = "library-meta";
    const source = text("span", "");
    const type = text("span", "");
    const date = text("time", "");
    meta.append(source, type, date);
    const file = text("small", "", "library-filename text-body-secondary");
    const live = text("small", "", "library-live text-body-secondary");
    const error = document.createElement("div");
    error.className = "library-error d-none";
    const errorHeader = document.createElement("div");
    errorHeader.className = "library-error-header";
    const errorMessage = text("strong", "");
    const copyError = text("button", t("js.copy_error_button"), "btn btn-sm btn-soft job-error-copy");
    copyError.type = "button";
    errorHeader.append(errorMessage, copyError);
    const errorHint = text("small", "");
    error.append(errorHeader, errorHint);
    const retry = text("small", "", "library-retry text-body-secondary d-none");
    const fullLog = linkAction(
      route("/jobs/log/" + encodeURIComponent(job.job_id)),
      t("common.full_log"),
      "btn btn-sm btn-soft library-full-log d-none"
    );
    fullLog.target = "_blank";
    fullLog.rel = "noreferrer";
    main.append(titleLink, meta, file, live, error, retry, fullLog);

    const state = document.createElement("div");
    state.className = "library-state";
    const status = text("span", "", "library-status");
    const progress = document.createElement("div");
    progress.className = "library-progress";
    progress.setAttribute("role", "progressbar");
    progress.setAttribute("aria-label", t("js.download_progress"));
    progress.setAttribute("aria-valuemin", "0");
    progress.setAttribute("aria-valuemax", "100");
    const progressTrack = document.createElement("div");
    progressTrack.className = "progress";
    const progressBar = document.createElement("div");
    progressBar.className = "progress-bar";
    progressTrack.append(progressBar);
    const progressLabel = text("small", "");
    progress.append(progressTrack, progressLabel);
    state.append(status, progress);

    const metrics = document.createElement("div");
    metrics.className = "library-metrics";
    const size = createMetric(t("common.size"));
    const speed = createMetric(t("common.speed"));
    const eta = createMetric(t("common.eta"));
    metrics.append(size.wrapper, speed.wrapper, eta.wrapper);

    const actions = document.createElement("div");
    actions.className = "library-actions";
    const primary = document.createElement("div");
    primary.className = "library-primary-action";
    const menu = document.createElement("details");
    menu.className = "library-menu";
    const menuButton = document.createElement("summary");
    menuButton.className = "library-menu-button";
    menuButton.append(svgIcon("more"));
    const menuPanel = document.createElement("div");
    menuPanel.className = "library-menu-panel";
    menu.append(menuButton, menuPanel);
    actions.append(primary, menu);
    if (!options.selectable) selectWrap.classList.add("d-none");
    if (options.compact) item.classList.add("library-item-compact");
    item.append(selectWrap, thumbnail, main, state, metrics, actions);
    itemReferences.set(item, { checkbox, thumbnail, image, placeholder, titleLink, source, type, date,
      file, live, error, errorMessage, errorHint, copyError, retry, fullLog,
      status, progress, progressBar, progressLabel, size: size.value, speed: speed.value, eta: eta.value,
      primary, menuButton, menuPanel, actionSignature: "", menuSignature: "" });
    updateLibraryItem(item, job);
    return item;
  };

  const errorHint = (job) => {
    const message = String(job.error_message || "").toLowerCase();
    if (message.includes("space") || message.includes("miejsca") || message.includes("disk")) return t("js.error_hint_storage");
    if (message.includes("timeout") || message.includes("network") || message.includes("webpage")) return t("js.error_hint_network");
    if (message.includes("ffmpeg") || message.includes("postprocessing") || message.includes("conversion")) return t("js.error_hint_ffmpeg");
    if (message.includes("format")) return t("js.error_hint_format");
    return t("js.error_hint_default");
  };

  const retryLabel = (job) => {
    const attempts = Number(job.auto_retry_attempts || 0);
    const max = Number(job.auto_retry_max_attempts || 0);
    if (job.next_retry_at) return t("js.auto_retry_scheduled", { attempts, max, time: dateLabel(job.next_retry_at) });
    if (job.status === "error" && max && attempts >= max) return t("js.auto_retry_exhausted", { attempts, max });
    return attempts ? t("js.auto_retry_attempts", { attempts, max: max || attempts }) : "";
  };

  function updateLibraryItem(item, job) {
    const refs = itemReferences.get(item);
    if (item.dataset.status !== job.status) item.dataset.status = job.status;
    if (refs.checkbox.value !== job.job_id) refs.checkbox.value = job.job_id;
    const selected = selectedJobIds.has(job.job_id);
    if (refs.checkbox.checked !== selected) refs.checkbox.checked = selected;
    const disabled = !isRemovableJob(job);
    if (refs.checkbox.disabled !== disabled) refs.checkbox.disabled = disabled;
    setNodeAttribute(refs.checkbox, "aria-label", t("js.select_job", { title: job.title }));
    const preview = job.file_exists && job.output_file
      ? route("/view/" + encodeManagedPath(job.output_file))
      : route("/jobs/" + encodeURIComponent(job.job_id));
    setNodeAttribute(refs.thumbnail, "href", preview);
    setNodeAttribute(refs.thumbnail, "aria-label", t("js.open_preview", { title: job.title }));
    const hasThumbnail = Boolean(job.thumbnail_exists && job.thumbnail_filename);
    refs.image.classList.toggle("d-none", !hasThumbnail);
    refs.placeholder.classList.toggle("d-none", hasThumbnail);
    if (hasThumbnail) {
      const src = route("/thumbnails/" + encodeURIComponent(job.thumbnail_filename));
      setNodeAttribute(refs.image, "src", src);
    }
    setNodeText(refs.titleLink, job.title);
    setNodeAttribute(refs.titleLink, "href", preview);
    setNodeText(refs.source, job.source_label);
    setNodeText(refs.type, downloadTypeLabel(job.download_type));
    setNodeText(refs.date, dateLabel(job.date_value));
    setNodeAttribute(refs.date, "datetime", job.date_value);
    setNodeText(refs.file, job.output_file || t("js.no_filename"));
    const live = liveInfo(job);
    setNodeText(refs.live, live);
    refs.live.classList.toggle("d-none", !live);
    setNodeText(refs.status, job.status_label);
    const nextStatusClass = "library-status " + statusClass(job.status);
    if (refs.status.className !== nextStatusClass) refs.status.className = nextStatusClass;
    setNodeAttribute(refs.progress, "aria-valuenow", job.progress);
    refs.progress.classList.toggle("d-none", !activeFilterStatuses.has(job.status));
    const progressWidth = job.progress + "%";
    if (refs.progressBar.style.width !== progressWidth) refs.progressBar.style.width = progressWidth;
    setNodeText(refs.progressLabel, job.progress.toFixed(0) + "%");
    setNodeText(refs.size, jobSize(job));
    setNodeText(refs.speed, job.speed || t("common.no_data"));
    setNodeText(refs.eta, job.eta || t("common.no_data"));
    const hasError = Boolean(job.error_message || job.status === "error");
    refs.error.classList.toggle("d-none", !hasError);
    setNodeText(refs.errorMessage, job.error_message || t("js.job_failed"));
    setNodeText(refs.errorHint, errorHint(job));
    refs.copyError.dataset.copyText = job.error_message || t("js.job_failed");
    const retryText = retryLabel(job);
    setNodeText(refs.retry, retryText);
    refs.retry.classList.toggle("d-none", !retryText);
    const logLines = (Array.isArray(job.recent_log_lines) ? job.recent_log_lines : job.log_lines) || [];
    refs.fullLog.classList.toggle("d-none", !logLines.some(Boolean));
    setNodeAttribute(refs.fullLog, "href", route("/jobs/log/" + encodeURIComponent(job.job_id)));
    const actionSignature = [job.status, job.can_stop, job.can_resume, job.can_retry, job.can_repeat, job.file_exists, job.output_file].join("|");
    if (refs.actionSignature !== actionSignature) {
      const restoreFocus = refs.primary.contains(document.activeElement);
      refs.primary.replaceChildren(primaryAction(job));
      if (restoreFocus) refs.primary.querySelector("a, button")?.focus({ preventScroll: true });
      refs.actionSignature = actionSignature;
    }
    const menuSignature = [job.can_repeat, job.can_delete, job.file_exists, job.output_file, job.title].join("|");
    if (refs.menuSignature !== menuSignature) {
      const restoreFocus = refs.menuPanel.contains(document.activeElement);
      refs.menuPanel.replaceChildren(menuActions(job));
      if (restoreFocus) refs.menuPanel.querySelector("a, button")?.focus({ preventScroll: true });
      refs.menuSignature = menuSignature;
    }
    const menuLabel = t("jobs.more_actions", { title: job.title });
    setNodeAttribute(refs.menuButton, "aria-label", menuLabel);
    setNodeAttribute(refs.menuButton, "title", menuLabel);
  }

  const reconcileList = (container, jobs, options = {}) => {
    if (!container) return;
    const existing = new Map(Array.from(container.querySelectorAll(":scope > .library-item[data-job-id]"))
      .map((item) => [item.dataset.jobId, item]));
    const wanted = new Set(jobs.map((job) => job.job_id));
    existing.forEach((item, jobId) => { if (!wanted.has(jobId)) item.remove(); });
    jobs.forEach((job, index) => {
      let item = existing.get(job.job_id);
      if (!item) item = createLibraryItem(job, options);
      else updateLibraryItem(item, job);
      const position = container.children[index];
      if (position !== item) container.insertBefore(item, position || null);
    });
  };

  const jobFilterConfig = {
    all: { matches: () => true, title: t("js.empty_no_jobs"), copy: t("jobs.empty_copy") },
    active: { matches: (job) => activeFilterStatuses.has(job.status), title: t("js.empty_no_active"), copy: t("jobs.empty_active_copy") },
    queued: { matches: (job) => queuedFilterStatuses.has(job.status), title: t("js.empty_no_queued"), copy: t("jobs.empty_queued_copy") },
    completed: { matches: (job) => job.status === "completed", title: t("js.empty_no_completed"), copy: t("jobs.empty_completed_copy") },
    errors: { matches: (job) => job.status === "error", title: t("js.empty_no_errors"), copy: t("jobs.empty_errors_copy") },
    stopped: { matches: (job) => job.status === "stopped", title: t("js.empty_no_stopped"), copy: t("jobs.empty_stopped_copy") },
    interrupted: { matches: (job) => job.status === "interrupted", title: t("js.empty_no_interrupted"), copy: t("jobs.empty_interrupted_copy") },
  };
  if (!jobFilterConfig[jobsFilter]) jobsFilter = "all";
  const matchesLibraryFilters = (job) => {
    const statusMatch = (jobFilterConfig[jobsFilter] || jobFilterConfig.all).matches(job);
    return statusMatch && (!jobsQuery || job.search_value.includes(jobsQuery));
  };
  const sortJobs = (jobs) => [...jobs].sort((left, right) => {
    if (jobsSort === "title") return left.title.localeCompare(right.title);
    if (jobsSort === "status") return left.status_label.localeCompare(right.status_label);
    const order = left.date_value.localeCompare(right.date_value);
    return jobsSort === "oldest" ? order : -order;
  });

  const updateSelectionControls = () => {
    const jobsById = new Map(lastSuccessfulJobs.map((job) => [job.job_id, job]));
    selectedJobIds.forEach((jobId) => {
      if (!jobsById.has(jobId) || !isRemovableJob(jobsById.get(jobId))) selectedJobIds.delete(jobId);
    });
    document.querySelectorAll(".job-select").forEach((checkbox) => {
      checkbox.checked = selectedJobIds.has(checkbox.value);
    });
    const inputs = document.getElementById("jobs-selected-inputs");
    if (inputs) {
      const currentIds = Array.from(inputs.querySelectorAll('input[name="job_ids"]')).map((input) => input.value);
      const nextIds = Array.from(selectedJobIds);
      if (currentIds.join("|") !== nextIds.join("|")) {
        inputs.replaceChildren();
        nextIds.forEach((jobId) => {
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "job_ids";
          input.value = jobId;
          inputs.append(input);
        });
      }
    }
    setNodeText(document.getElementById("jobs-selected-count"), selectedJobIds.size);
    const submit = document.getElementById("jobs-bulk-submit");
    if (submit) submit.disabled = selectedJobIds.size === 0;
    const visible = lastSuccessfulJobs.filter(matchesLibraryFilters).filter(isRemovableJob);
    const selectedVisible = visible.filter((job) => selectedJobIds.has(job.job_id)).length;
    const selectAll = document.getElementById("jobs-select-all");
    if (selectAll) {
      selectAll.disabled = visible.length === 0;
      selectAll.checked = visible.length > 0 && selectedVisible === visible.length;
      selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
    }
  };

  const updateFilterControls = () => {
    document.querySelectorAll("[data-jobs-filter]").forEach((button) => {
      const active = button.dataset.jobsFilter === jobsFilter;
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("btn-primary", active);
      button.classList.toggle("btn-soft", !active);
    });
    document.querySelectorAll("[data-jobs-filter-count]").forEach((count) => {
      const config = jobFilterConfig[count.dataset.jobsFilterCount] || jobFilterConfig.all;
      setNodeText(count, lastSuccessfulJobs.filter(config.matches).length);
    });
  };

  const updateLibraryPresentation = () => {
    if (!libraryList) return;
    const ordered = sortJobs(lastSuccessfulJobs);
    reconcileList(libraryList, ordered, { selectable: true });
    const visibleIds = new Set(ordered.filter(matchesLibraryFilters).map((job) => job.job_id));
    libraryList.querySelectorAll(":scope > .library-item").forEach((item) => {
      item.classList.toggle("d-none", !visibleIds.has(item.dataset.jobId));
    });
    setNodeText(document.getElementById("jobs-result-count"), t("jobs.results", { count: visibleIds.size }));
    const empty = document.getElementById("jobs-empty");
    empty?.classList.toggle("d-none", visibleIds.size > 0);
    const filtered = Boolean(jobsQuery || jobsFilter !== "all");
    const filterEmpty = jobFilterConfig[jobsFilter] || jobFilterConfig.all;
    const emptyTitle = jobsQuery ? t("jobs.empty_search") : filterEmpty.title;
    const emptyCopy = jobsQuery ? t("jobs.empty_search_copy") : filterEmpty.copy;
    setNodeText(document.getElementById("jobs-empty-title"), emptyTitle);
    setNodeText(document.getElementById("jobs-empty-copy"), emptyCopy);
    document.getElementById("jobs-empty-show-all")?.classList.toggle("d-none", !filtered);
    const retryFailed = document.getElementById("jobs-retry-failed");
    if (retryFailed) retryFailed.disabled = !lastSuccessfulJobs.some((job) => job.can_retry === true);
    updateFilterControls();
    updateSelectionControls();
  };

  const updateStats = (jobs) => {
    setNodeText(document.getElementById("stat-active"), jobs.filter((job) => activeFilterStatuses.has(job.status)).length);
    setNodeText(document.getElementById("stat-queued"), jobs.filter((job) => queuedFilterStatuses.has(job.status)).length);
    setNodeText(document.getElementById("stat-errors"), jobs.filter((job) => job.status === "error").length);
    const activeCount = jobs.filter(isActiveJob).length;
    const badge = document.getElementById("active-jobs-badge");
    setNodeText(badge, activeCount);
    setNodeAttribute(badge, "aria-label", t("nav.active_jobs", { count: activeCount }));
  };
  const updateDashboardLists = (jobs) => {
    const active = sortJobs(jobs.filter((job) => activeFilterStatuses.has(job.status))).slice(0, 3);
    const completed = sortJobs(jobs.filter((job) => job.status === "completed")).slice(0, 5);
    reconcileList(activeDownloadsList, active, { compact: true });
    reconcileList(recentDownloadsList, completed, { compact: true });
    document.getElementById("active-downloads-section")?.classList.toggle("d-none", active.length === 0);
    document.getElementById("recent-downloads-empty")?.classList.toggle("d-none", completed.length > 0);
  };
  const updateJobsView = (rawJobs) => {
    lastSuccessfulJobs = rawJobs.map(normalizeJob);
    updateStats(lastSuccessfulJobs);
    updateDashboardLists(lastSuccessfulJobs);
    updateLibraryPresentation();
  };
  const setJobsFilter = (filter) => {
    jobsFilter = jobFilterConfig[filter] ? filter : "all";
    if (libraryPageVisible) {
      const url = new URL(window.location.href);
      if (jobsFilter === "all") url.searchParams.delete("filter");
      else url.searchParams.set("filter", jobsFilter);
      window.history.replaceState({}, "", url);
    }
    updateLibraryPresentation();
  };

  document.querySelectorAll("[data-jobs-filter]").forEach((button) => {
    button.addEventListener("click", () => setJobsFilter(button.dataset.jobsFilter || "all"));
  });
  document.getElementById("jobs-search")?.addEventListener("input", (event) => {
    jobsQuery = event.target.value.trim().toLocaleLowerCase();
    updateLibraryPresentation();
  });
  document.getElementById("jobs-sort")?.addEventListener("change", (event) => {
    jobsSort = event.target.value;
    updateLibraryPresentation();
  });
  document.getElementById("jobs-empty-show-all")?.addEventListener("click", () => {
    const search = document.getElementById("jobs-search");
    if (search) search.value = "";
    jobsQuery = "";
    setJobsFilter("all");
  });
  document.getElementById("jobs-select-all")?.addEventListener("change", (event) => {
    lastSuccessfulJobs.filter(matchesLibraryFilters).filter(isRemovableJob).forEach((job) => {
      if (event.target.checked) selectedJobIds.add(job.job_id);
      else selectedJobIds.delete(job.job_id);
    });
    updateSelectionControls();
  });

  const bulkForm = document.getElementById("jobs-bulk-form");
  const bulkAction = document.getElementById("jobs-bulk-action");
  bulkForm?.addEventListener("submit", (event) => {
    const action = bulkAction?.value || "delete_jobs";
    if (!selectedJobIds.size) {
      event.preventDefault();
      return;
    }
    const actionLabels = { delete_jobs: t("js.history_delete_entries"),
      delete_files: t("js.history_delete_files"), repeat: t("js.history_repeat") };
    if (!window.confirm(t("js.history_action_confirm", { action: actionLabels[action], count: selectedJobIds.size }))) {
      event.preventDefault();
      return;
    }
    bulkForm.action = action === "delete_jobs" ? route("/jobs/delete") : route("/history/jobs/bulk");
    const actionValue = document.getElementById("jobs-bulk-action-value");
    if (actionValue) actionValue.value = action;
  });
  document.getElementById("jobs-retry-failed-form")?.addEventListener("submit", (event) => {
    const count = lastSuccessfulJobs.filter((job) => job.can_retry === true).length;
    if (!count || !window.confirm(t("js.retry_failed_jobs", { count }))) event.preventDefault();
  });

  const copyTextToClipboard = async (value) => {
    if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
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
    const original = button.textContent;
    try {
      await copyTextToClipboard(button.dataset.copyText || "");
      button.textContent = t("js.copied");
    } catch (error) {
      console.error(t("js.copy_error"), error);
      button.textContent = t("js.copy_error");
    } finally {
      window.setTimeout(() => { button.textContent = original; }, 1600);
    }
  });

  const notifyNewJobErrors = (jobs) => {
    const hadSnapshot = knownJobStatuses.size > 0;
    jobs.forEach((job) => {
      const previous = knownJobStatuses.get(job.job_id);
      if (hadSnapshot && job.status === "error" && previous !== "error") {
        showAppToast(t("js.job_error_toast", { title: job.title || job.job_id }), {
          type: "danger", actionHref: route("/jobs/log/" + encodeURIComponent(job.job_id)),
          actionLabel: t("common.open_log") });
      }
    });
    knownJobStatuses = new Map(jobs.map((job) => [job.job_id, job.status]));
  };
  const pollingDelay = () => {
    if (lastSuccessfulJobs.some(isActiveJob)) return 1000;
    return libraryPageVisible ? 3000 : 5000;
  };
  const scheduleJobsRefresh = () => {
    window.clearTimeout(jobsRefreshTimer);
    if (!document.hidden && document.getElementById("active-jobs-badge")) {
      jobsRefreshTimer = window.setTimeout(refreshJobs, pollingDelay());
    }
  };
  async function refreshJobs() {
    if (!document.getElementById("active-jobs-badge") || jobsRefreshInProgress || document.hidden) return;
    jobsRefreshInProgress = true;
    try {
      const response = await fetch(route("/api/jobs"), { cache: "no-store", headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.jobs)) throw new Error(t("js.bad_api"));
      notifyNewJobErrors(payload.jobs);
      updateJobsView(payload.jobs);
      document.getElementById("jobs-refresh-error")?.classList.add("d-none");
    } catch (error) {
      console.error(t("js.refresh_failed"), error);
      document.getElementById("jobs-refresh-error")?.classList.remove("d-none");
    } finally {
      jobsRefreshInProgress = false;
      scheduleJobsRefresh();
    }
  }

  try {
    const initialJobs = JSON.parse(document.getElementById("initial-jobs")?.textContent || "[]");
    if (Array.isArray(initialJobs)) updateJobsView(initialJobs);
  } catch (error) {
    console.error(t("js.bad_api"), error);
  }
  refreshJobs();
  document.addEventListener("visibilitychange", () => {
    window.clearTimeout(jobsRefreshTimer);
    if (!document.hidden) refreshJobs();
  });
  window.addEventListener("focus", refreshJobs);

})();
