(() => {
  "use strict";

  const ingressPath = document.querySelector('meta[name="ingress-path"]')?.content || "";
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let allowedHosts = new Set();
  try {
    allowedHosts = new Set(JSON.parse(document.getElementById("allowed-hosts")?.textContent || "[]"));
  } catch (error) {
    console.error("Nie można odczytać listy obsługiwanych domen:", error);
  }

  const route = (path) => `${ingressPath}${path}`;

  const text = (tag, value, className = "") => {
    const node = document.createElement(tag);
    node.textContent = value ?? "";
    if (className) node.className = className;
    return node;
  };

  const isValidMediaUrl = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && allowedHosts.has(url.hostname.toLowerCase());
    } catch {
      return false;
    }
  };

  document.querySelectorAll(".url-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const input = form.querySelector(".media-url");
      const valid = input && isValidMediaUrl(input.value);
      if (!valid) {
        event.preventDefault();
        event.stopPropagation();
        input?.classList.add("is-invalid");
        return;
      }
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

  document.querySelectorAll(".download-form").forEach((form) => {
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

    downloadType.addEventListener("change", syncFormatId);
    formatId.addEventListener("input", () => {
      if (formatId.value.trim()) formatId.classList.remove("is-invalid");
    });
    form.addEventListener("submit", (event) => {
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
        downloadType.value = "format";
        syncFormatId();
        formatId.value = button.dataset.formatId || "";
        formatId.classList.remove("is-invalid");
        form.requestSubmit();
      });
    });
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

    const addOptions = (select, values) => {
      values.forEach((value) => {
        const option = text("option", value);
        option.value = value;
        select?.append(option);
      });
    };

    addOptions(typeFilter, [...new Set(records.map((item) => item.dataset.historyType).filter(Boolean))].sort());
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

  let activeJobStatuses = new Set();
  try {
    activeJobStatuses = new Set(JSON.parse(document.getElementById("active-job-statuses")?.textContent || "[]"));
  } catch (error) {
    console.error("Nie można odczytać listy aktywnych statusów:", error);
  }
  const isActiveJob = (job) => activeJobStatuses.has(job.status);

  const statusBadge = (job) => {
    const colors = {
      pending: "text-bg-secondary",
      downloading: "text-bg-primary",
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

  const outputLink = (job) => {
    if (!job.output_file) return text("span", "-", "text-body-secondary");
    const link = text("a", "Pobierz", "btn btn-sm btn-soft");
    link.href = route(`/downloaded/${encodeURIComponent(job.output_file)}`);
    link.title = job.output_file;
    return link;
  };

  const actionForm = (action, label, className) => {
    const form = document.createElement("form");
    form.method = "post";
    form.action = action;
    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "_csrf_token";
    token.value = csrfToken;
    const button = text("button", label, className);
    button.type = "submit";
    form.append(token, button);
    return form;
  };

  const jobActions = (job) => {
    const actions = document.createElement("span");
    actions.className = "d-flex gap-2";
    if (job.is_live && ["pending", "downloading"].includes(job.status)) {
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
    return actions;
  };

  const renderTable = (jobs) => {
    const body = document.getElementById("jobs-table-body");
    if (!body) return;
    body.replaceChildren();
    jobs.forEach((job) => {
      const row = document.createElement("tr");
      const titleCell = document.createElement("td");
      titleCell.append(text("strong", job.title), text("small", job.error_message || "", "job-error d-block text-danger"));
      const typeCell = text("td", job.download_type);
      const statusCell = document.createElement("td");
      statusCell.append(statusBadge(job));
      const progressCell = document.createElement("td");
      progressCell.append(progressBar(job), text("small", `${job.progress || 0}%`, "text-body-secondary"));
      const speedCell = text("td", job.speed || "-");
      const etaCell = text("td", job.eta || "-");
      const outputCell = document.createElement("td");
      outputCell.append(outputLink(job));
      const actionCell = document.createElement("td");
      actionCell.append(jobActions(job));
      row.append(titleCell, typeCell, statusCell, progressCell, speedCell, etaCell, outputCell, actionCell);
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
      const meta = text("small", `${job.download_type} | ${job.speed || "-"} | ETA ${job.eta || "-"}`, "d-block text-body-secondary mb-2");
      const status = statusBadge(job);
      const progress = progressBar(job);
      progress.classList.add("my-2");
      const error = text("small", job.error_message || "", "d-block text-danger mb-2");
      const actions = document.createElement("div");
      actions.className = "d-flex gap-2 align-items-center";
      actions.append(outputLink(job), jobActions(job));
      card.append(heading, meta, status, progress, text("small", `${job.progress || 0}%`, "text-body-secondary"), error, actions);
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
    document.getElementById("jobs-empty")?.classList.toggle("d-none", jobs.length > 0);
    renderTable(jobs);
    renderCards(jobs);
  };

  const setJobsRefreshError = (visible) => {
    document.getElementById("jobs-refresh-error")?.classList.toggle("d-none", !visible);
  };

  let lastSuccessfulJobs = null;
  let jobsRefreshInProgress = false;

  const refreshJobs = async () => {
    if (!document.getElementById("active-jobs-badge") || jobsRefreshInProgress) return;
    jobsRefreshInProgress = true;
    try {
      const response = await fetch(route("/api/jobs"), { headers: { Accept: "application/json" } });
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
    window.setInterval(refreshJobs, 2500);
  }
})();
