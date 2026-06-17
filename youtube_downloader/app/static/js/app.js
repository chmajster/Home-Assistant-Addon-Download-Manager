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
      const detectedUrls = pastedUrls(input?.value || "");
      const urls = detectedUrls.length > 1 ? selectedBulkUrls() : detectedUrls;
      const invalidUrls = urls.filter((url) => !isValidMediaUrl(url));
      if (!urls.length || invalidUrls.length) {
        event.preventDefault();
        event.stopPropagation();
        input?.classList.add("is-invalid");
        if (feedback) {
          feedback.textContent = !urls.length
            ? "Wklej co najmniej jeden adres URL."
            : `Niepoprawne URL-e: ${invalidUrls.join(", ")}`;
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
      const button = form.querySelector(".analyze-submit");
      button?.setAttribute("disabled", "disabled");
      button?.setAttribute("aria-disabled", "true");
      button?.querySelector(".spinner-border")?.classList.remove("d-none");
      const label = button?.querySelector(".analyze-submit-label");
      if (label) label.textContent = "Analizuję...";
      form.querySelector(".analyze-loading")?.classList.remove("d-none");
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

  const customPlayerButton = (label, icon, className = "") => {
    const button = document.createElement("button");
    button.className = `custom-player-button ${className}`.trim();
    button.type = "button";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.textContent = icon;
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
    ...readJsonStorage(playerSettingsStorageKey, {}),
  });

  const writePlayerSettings = (settings) => {
    const normalized = {
      volume: Math.min(1, Math.max(0, Number(settings.volume) || 0)),
      muted: Boolean(settings.muted),
      playbackRate: Number(settings.playbackRate) || 1,
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

  const enhanceCustomPlayer = (player) => {
    const media = player.querySelector(".custom-player-media");
    if (!(media instanceof HTMLMediaElement) || player.dataset.customPlayerReady) return;
    player.dataset.customPlayerReady = "true";
    const storedSettings = readPlayerSettings();
    const speedOptions = [0.75, 1, 1.25, 1.5, 2];
    const storedVolume = Number(storedSettings.volume);
    media.volume = Number.isFinite(storedVolume) ? Math.min(1, Math.max(0, storedVolume)) : 1;
    media.muted = Boolean(storedSettings.muted);
    media.playbackRate = speedOptions.includes(Number(storedSettings.playbackRate))
      ? Number(storedSettings.playbackRate)
      : 1;
    if (media instanceof HTMLVideoElement && !player.hasAttribute("tabindex")) {
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

    const play = customPlayerButton("Odtwórz", "\u25b6", "custom-player-play");
    const stop = customPlayerButton("Stop", "\u25a0");
    const rewind30 = customPlayerButton("Cofnij 30 sekund", "-30");
    const rewind = customPlayerButton("Cofnij 10 sekund", "\u21b6");
    const forward = customPlayerButton("Przewiń 10 sekund", "\u21b7");
    const forward30 = customPlayerButton("Przewiń 30 sekund", "+30");
    const loop = customPlayerButton("Pętla", "\u221e", "custom-player-loop");
    loop.setAttribute("aria-pressed", "false");
    const mute = customPlayerButton("Wycisz", "\ud83d\udd0a", "custom-player-mute");
    const fullscreen = customPlayerButton("Pełny ekran", "\u26f6", "custom-player-fullscreen");
    const pip = customPlayerButton("Picture-in-Picture", "PiP", "custom-player-pip");
    const time = text("span", "0:00 / 0:00", "custom-player-time");
    const speed = document.createElement("select");
    speed.className = "custom-player-speed";
    speed.setAttribute("aria-label", "Prędkość odtwarzania");
    speedOptions.forEach((option) => {
      const speedOption = document.createElement("option");
      speedOption.value = String(option);
      speedOption.textContent = `${option}x`;
      speedOption.selected = media.playbackRate === option;
      speed.append(speedOption);
    });
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
    const progressRow = document.createElement("div");
    progressRow.className = "custom-player-row";
    progressRow.append(progress);
    const mainRow = document.createElement("div");
    mainRow.className = "custom-player-row custom-player-main-row";
    const transport = document.createElement("div");
    transport.className = "custom-player-row";
    transport.append(play, stop, rewind30, rewind, forward, forward30, loop, time);
    const audio = document.createElement("div");
    audio.className = "custom-player-row custom-player-volume-row";
    audio.append(speed, mute, volume);
    if (media instanceof HTMLVideoElement && document.pictureInPictureEnabled) audio.append(pip);
    audio.append(fullscreen);
    mainRow.append(transport, audio);
    controls.append(progressRow, mainRow);
    player.append(controls);
    if (!supportsFullscreen(player) && !media.webkitEnterFullscreen) fullscreen.hidden = true;

    const previewThumbnailUrl = player.dataset.previewThumbnail || "";
    let seekPreview = null;
    let seekPreviewTime = null;
    if (media instanceof HTMLVideoElement) {
      seekPreview = document.createElement("div");
      seekPreview.className = "custom-player-seek-preview";
      if (previewThumbnailUrl) {
        const seekPreviewImage = document.createElement("img");
        seekPreviewImage.className = "custom-player-seek-preview-image";
        seekPreviewImage.alt = "";
        seekPreviewImage.loading = "lazy";
        seekPreviewImage.src = previewThumbnailUrl;
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

    let controlsTimer = null;
    let seeking = false;
    const isVideo = media instanceof HTMLVideoElement;
    const updateRangeFill = (range, percent, property) => {
      range.style.setProperty(property, `${Math.min(100, Math.max(0, percent))}%`);
    };
    const hideControls = () => {
      if (!isVideo || media.paused || seeking || player.matches(":focus-within")) return;
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
      fullscreen.textContent = active ? "\u2715" : "\u26f6";
      fullscreen.setAttribute("aria-label", active ? "Zamknij pełny ekran" : "Pełny ekran");
      fullscreen.title = active ? "Zamknij pełny ekran" : "Pełny ekran";
    };
    const syncPlay = () => {
      const paused = media.paused;
      play.textContent = paused ? "\u25b6" : "\u23f8";
      play.setAttribute("aria-label", paused ? "Odtwórz" : "Pauza");
      play.title = paused ? "Odtwórz" : "Pauza";
      player.classList.toggle("custom-player-playing", !paused);
      if (overlayIcon) overlayIcon.textContent = paused ? "\u25b6" : "\u23f8";
      showControls();
    };
    const syncMute = () => {
      const muted = media.muted || media.volume === 0;
      mute.textContent = muted ? "\ud83d\udd07" : "\ud83d\udd0a";
      mute.setAttribute("aria-label", muted ? "Włącz dźwięk" : "Wycisz");
      mute.title = muted ? "Włącz dźwięk" : "Wycisz";
      volume.value = String(media.muted ? 0 : media.volume);
      updateRangeFill(volume, Number(volume.value) * 100, "--volume-fill");
    };
    const persistSettings = () => writePlayerSettings({
      volume: media.volume,
      muted: media.muted,
      playbackRate: media.playbackRate,
    });
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
      seekPreview.style.left = `${previewX}px`;
      seekPreviewTime.textContent = formatMediaTime(ratio * duration);
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
    stop.addEventListener("click", () => {
      media.pause();
      media.currentTime = 0;
    });
    rewind30.addEventListener("click", () => seekBy(-30));
    rewind.addEventListener("click", () => seekBy(-10));
    forward.addEventListener("click", () => seekBy(10));
    forward30.addEventListener("click", () => seekBy(30));
    loop.addEventListener("click", () => {
      media.loop = !media.loop;
      loop.classList.toggle("custom-player-button-active", media.loop);
      loop.setAttribute("aria-pressed", String(media.loop));
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
      media.playbackRate = Number(speed.value) || 1;
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
    pip.addEventListener("click", async () => {
      if (!(media instanceof HTMLVideoElement) || !document.pictureInPictureEnabled) return;
      try {
        if (document.pictureInPictureElement === media) await document.exitPictureInPicture();
        else await media.requestPictureInPicture();
      } catch (error) {
        console.error("Nie można uruchomić Picture-in-Picture:", error);
      }
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
      speed.value = String(media.playbackRate);
      persistSettings();
    });
    media.addEventListener("ended", () => writePlayerPosition(media));
    syncPlay();
    syncMute();
    syncTime();
    syncFullscreen();
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
  let jobsFilter = document.getElementById("jobs-filter-state")?.dataset.initialFilter === "errors" ? "errors" : "all";

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

  const filteredJobs = (jobs) => jobsFilter === "errors" ? jobs.filter((job) => job.status === "error") : jobs;

  const setJobsFilter = (filter, updateUrl = true) => {
    jobsFilter = filter === "errors" ? "errors" : "all";
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
      if (jobsFilter === "errors") url.searchParams.set("filter", "errors");
      else url.searchParams.delete("filter");
      window.history.replaceState({}, "", url);
    }
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
