(() => {
  "use strict";

  const ingressPath = document.querySelector('meta[name="ingress-path"]')?.content || "";
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const jobsViewVisible = Boolean(document.getElementById("jobs-table-body"));
  const jobsRefreshIntervalMs = jobsViewVisible ? 500 : 2500;
  const themeStorageKey = "media-web-downloader-theme";
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

  document.querySelectorAll(".url-form").forEach((form) => {
    const input = form.querySelector(".media-url");
    const feedback = form.querySelector(".invalid-feedback");
    const syncTextareaHeight = () => {
      if (!(input instanceof HTMLTextAreaElement)) return;
      input.style.height = "auto";
      input.style.height = `${Math.max(input.scrollHeight, 54)}px`;
    };
    input?.addEventListener("input", syncTextareaHeight);
    input?.addEventListener("paste", () => setTimeout(syncTextareaHeight, 0));
    form.addEventListener("submit", (event) => {
      const urls = pastedUrls(input?.value || "");
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
    syncFormatId();

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
          button.textContent = open ? "Zamknij" : "Odtwórz tutaj";
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
    const lines = Array.isArray(job.log_lines) ? job.log_lines.filter(Boolean) : [];
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

  const jobThumbnail = (job, mobile = false) => {
    if (job.thumbnail_exists && job.thumbnail_filename) {
      const image = document.createElement("img");
      image.className = `job-thumbnail${mobile ? " job-thumbnail-mobile mb-3" : ""}`;
      image.src = route(`/thumbnails/${encodeURIComponent(job.thumbnail_filename)}`);
      image.alt = "";
      image.loading = "lazy";
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
        text("strong", job.title),
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
      const heading = text("strong", job.title, "d-block");
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
