(() => {
  "use strict";

  const ingressPath = document.querySelector('meta[name="ingress-path"]')?.content || "";
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const allowedHosts = new Set([
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "music.youtube.com",
    "instagram.com",
    "www.instagram.com",
    "kick.com",
    "www.kick.com",
  ]);

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
  });

  const activeJobStatuses = new Set(["pending", "downloading"]);
  const isActiveJob = (job) => activeJobStatuses.has(job.status);

  const statusBadge = (job) => {
    const colors = {
      pending: "text-bg-secondary",
      downloading: "text-bg-primary",
      completed: "text-bg-success",
      error: "text-bg-danger",
      stopped: "text-bg-warning",
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
    const link = text("a", job.output_file);
    link.href = route(`/downloaded/${encodeURIComponent(job.output_file)}`);
    return link;
  };

  const stopForm = (job) => {
    if (!job.is_live || !isActiveJob(job)) return text("span", "");
    const form = document.createElement("form");
    form.method = "post";
    form.action = route(`/live/stop/${encodeURIComponent(job.job_id)}`);
    const token = document.createElement("input");
    token.type = "hidden";
    token.name = "_csrf_token";
    token.value = csrfToken;
    const button = text("button", "Zatrzymaj", "btn btn-sm btn-outline-danger");
    button.type = "submit";
    form.append(token, button);
    return form;
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
      actionCell.append(stopForm(job));
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
      actions.append(outputLink(job), stopForm(job));
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
