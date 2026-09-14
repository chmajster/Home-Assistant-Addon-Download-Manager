/* Independent navigation and download form; the legacy bundle still owns jobs/player. */
(() => {
  "use strict";
  const REQUEST_TIMEOUT_MS = 120000;
  const initializedForms = new WeakSet();

  // Keep the separator contract used by the server's bulk URL parser.
  const parseUrls = (value) => [...new Set(String(value || "")
    .split(/[\n\r,;]+/).map((item) => item.trim()).filter(Boolean))];
  const validMediaUrl = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol)
        && Boolean(url.hostname) && !url.username && !url.password && !url.port;
    } catch { return false; }
  };
  const readMessages = (id) => {
    try { return JSON.parse(document.getElementById(id)?.textContent || "{}"); }
    catch { return {}; }
  };
  const translate = (messages, key, values = {}) => Object.entries(values).reduce(
    (result, [name, value]) => result.replaceAll(`{${name}}`, String(value ?? "")),
    messages[key] || key
  );

  function initNavigation(root = document) {
    const toggle = root.querySelector("[data-workspace-toggle]");
    const nav = root.querySelector(".workspace-nav");
    if (!toggle || !nav) return;
    const media = window.matchMedia("(max-width: 1023px)");
    document.body.classList.add("workspace-enhanced");
    const setOpen = (open) => {
      nav.toggleAttribute("data-open", open);
      toggle.setAttribute("aria-expanded", String(open));
    };
    const resize = () => {
      toggle.hidden = !media.matches;
      if (media.matches && nav.contains(document.activeElement)) toggle.focus();
      setOpen(false);
    };
    toggle.addEventListener("click", () => setOpen(!nav.hasAttribute("data-open")));
    nav.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && media.matches) {
        setOpen(false);
        toggle.focus();
      }
    });
    nav.addEventListener("click", (event) => {
      if (media.matches && event.target.closest("a[href]")) setOpen(false);
    });
    media.addEventListener("change", resize);
    resize();
  }

  async function copyText(value) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        return;
      }
    } catch { /* Fall back when WebView permissions reject the clipboard API. */ }
    const previousFocus = document.activeElement;
    const input = document.createElement("textarea");
    input.value = value;
    input.style.cssText = "position:fixed;left:-9999px;top:0";
    document.body.append(input);
    try {
      input.select();
      if (!document.execCommand("copy")) throw new Error("Clipboard unavailable");
    } finally {
      input.remove();
      previousFocus?.focus?.({ preventScroll: true });
    }
  }

  function initDownloadForm(form, messages) {
    if (initializedForms.has(form)) return;
    initializedForms.add(form);
    const t = (key, values) => translate(messages, key, values);
    const input = form.querySelector(".media-url");
    const feedback = form.querySelector(".download-feedback");
    const review = form.querySelector("[data-bulk-url-review]");
    const list = form.querySelector("[data-bulk-url-list]");
    const summary = form.querySelector("[data-bulk-url-summary]");
    const clear = form.querySelector("[data-url-clear]");
    const copyInvalid = form.querySelector("[data-bulk-url-copy-invalid]");
    const removeInvalid = form.querySelector("[data-bulk-url-remove-invalid]");
    const loading = form.querySelector(".analyze-loading");
    const analyze = form.querySelector(".analyze-submit");
    if (!input || !feedback || !list || !review) return;
    let pending = false;
    let generation = 0;
    let controller = null;
    let restoreControls = () => {};

    const message = (value, type = "danger", jobsLink = false) => {
      feedback.replaceChildren(document.createTextNode(value));
      feedback.className = `download-feedback alert alert-${type}`;
      feedback.setAttribute("role", type === "danger" ? "alert" : "status");
      feedback.hidden = false;
      if (jobsLink) {
        const link = document.createElement("a");
        link.href = form.dataset.jobsUrl;
        link.textContent = t("nav.go_jobs");
        feedback.append(link);
      }
    };
    const selectedUrls = () => [...list.querySelectorAll(".bulk-url-select:checked")]
      .map((checkbox) => checkbox.value);
    const syncSummary = () => {
      const count = list.querySelectorAll(".bulk-url-select").length;
      const invalidCount = list.querySelectorAll(".bulk-url-item-invalid").length;
      if (summary) summary.textContent = t("js.url_selected", { selected: selectedUrls().length, total: count });
      if (copyInvalid) copyInvalid.disabled = pending || invalidCount === 0;
      if (removeInvalid) removeInvalid.disabled = pending || invalidCount === 0;
      if (clear) clear.disabled = pending || !input.value;
    };
    const renderReview = () => {
      const previous = new Map([...list.querySelectorAll(".bulk-url-select")]
        .map((checkbox) => [checkbox.value, checkbox.checked]));
      const urls = parseUrls(input.value);
      review.hidden = urls.length <= 1;
      list.replaceChildren();
      urls.forEach((url, index) => {
        const valid = validMediaUrl(url);
        const row = document.createElement("div");
        row.className = `bulk-url-item${valid ? "" : " bulk-url-item-invalid"}`;
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "form-check-input bulk-url-select";
        checkbox.value = url;
        checkbox.checked = valid && (previous.get(url) ?? true);
        checkbox.disabled = pending || !valid;
        checkbox.addEventListener("change", syncSummary);
        const text = document.createElement("span");
        text.className = "bulk-url-text";
        text.textContent = url;
        const status = document.createElement("small");
        status.className = "bulk-url-status";
        status.textContent = valid ? t("js.link", { number: index + 1 }) : t("js.invalid_url_item");
        text.append(status);
        label.append(checkbox, text);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "bulk-url-remove";
        remove.textContent = "×";
        remove.disabled = pending;
        remove.setAttribute("aria-label", t("js.remove_link", { number: index + 1 }));
        remove.addEventListener("click", () => {
          input.value = parseUrls(input.value).filter((item) => item !== url).join("\n");
          renderReview();
          input.focus();
        });
        row.append(label, remove);
        list.append(row);
      });
      syncSummary();
    };
    const reset = () => {
      restoreControls();
      restoreControls = () => {};
      pending = false;
      form.setAttribute("aria-busy", "false");
      if (loading) loading.hidden = true;
      form.querySelectorAll(".spinner-border").forEach((spinner) => spinner.classList.add("d-none"));
      syncSummary();
    };
    const busy = (submitter, quick) => {
      pending = true;
      form.setAttribute("aria-busy", "true");
      const controls = [...form.querySelectorAll("button, input[type=checkbox]")]
        .map((node) => ({ node, disabled: node.disabled }));
      const readOnly = input.readOnly;
      controls.forEach(({ node }) => { node.disabled = true; });
      input.readOnly = true;
      restoreControls = () => {
        controls.forEach(({ node, disabled }) => { node.disabled = disabled; });
        input.readOnly = readOnly;
      };
      if (loading) {
        loading.hidden = false;
        const title = loading.querySelector("[data-loading-title]");
        if (title) title.textContent = t(quick ? "index.loading_download" : "index.loading_analyze");
      }
      submitter?.querySelector(".spinner-border")?.classList.remove("d-none");
    };
    input.addEventListener("input", () => {
      if (pending) return;
      input.classList.remove("is-invalid");
      input.removeAttribute("aria-invalid");
      feedback.hidden = true;
      renderReview();
    });
    input.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.isComposing && !pending) {
        event.preventDefault();
        form.requestSubmit(analyze);
      }
    });
    clear?.addEventListener("click", () => {
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
    });
    form.querySelectorAll("[data-bulk-url-select]").forEach((button) => {
      button.addEventListener("click", () => {
        list.querySelectorAll(".bulk-url-select:not(:disabled)").forEach((checkbox) => {
          checkbox.checked = button.dataset.bulkUrlSelect === "all";
        });
        syncSummary();
      });
    });
    copyInvalid?.addEventListener("click", async () => {
      try {
        await copyText(parseUrls(input.value).filter((url) => !validMediaUrl(url)).join("\n"));
        message(t("js.copied"), "info");
      } catch { message(t("copy_failed")); }
    });
    removeInvalid?.addEventListener("click", () => {
      input.value = parseUrls(input.value).filter(validMediaUrl).join("\n");
      renderReview();
    });
    form.addEventListener("submit", async (event) => {
      if (pending) { event.preventDefault(); return; }
      const quick = Boolean(event.submitter?.matches("[data-quick-download-submit]"));
      const detected = parseUrls(input.value);
      const urls = detected.length > 1 ? selectedUrls() : detected;
      const invalid = urls.filter((url) => !validMediaUrl(url));
      if (!urls.length || invalid.length || (quick && urls.length !== 1)) {
        event.preventDefault();
        input.classList.add("is-invalid");
        input.setAttribute("aria-invalid", "true");
        message(!urls.length ? t("js.paste_one") : invalid.length
          ? t("js.invalid_urls", { urls: invalid.join(", ") }) : t("js.quick_one"));
        input.focus();
        return;
      }
      input.classList.remove("is-invalid");
      input.removeAttribute("aria-invalid");
      feedback.hidden = true;
      const submittedValue = urls.join("\n");
      input.value = submittedValue;
      const body = new FormData(form); // Capture before disabling controls.
      const action = event.submitter?.formAction || form.action;
      busy(event.submitter, quick);
      if (!quick) return; // Native analysis navigation retains CSRF and Ingress.
      event.preventDefault();
      const attempt = ++generation;
      controller = new AbortController();
      const activeController = controller;
      const timeout = window.setTimeout(() => activeController.abort(), REQUEST_TIMEOUT_MS);
      try {
        const response = await fetch(action, {
          method: "POST", body, credentials: "same-origin",
          headers: { Accept: "application/json" }, signal: activeController.signal,
        });
        if (attempt !== generation) return;
        if (response.redirected || !(response.headers.get("content-type") || "").toLowerCase().includes("application/json")) {
          throw new Error(t("session_expired"));
        }
        const payload = await response.json();
        if (attempt !== generation) return;
        if (!response.ok || !payload || payload.ok !== true) {
          throw new Error(typeof payload?.message === "string" ? payload.message : t("js.quick_failed"));
        }
        if (payload.clear_url && input.value === submittedValue) {
          input.value = "";
          renderReview();
        }
        const type = ["success", "warning", "danger", "info"].includes(payload.category) ? payload.category : "success";
        message(typeof payload.message === "string" ? payload.message : t("js.quick_added_plain"), type, Boolean(payload.queued));
      } catch (error) {
        // Do not skip cleanup when a request fails in a background tab.
        if (attempt === generation) {
          message(error instanceof TypeError || error?.name === "AbortError"
            ? t("request_uncertain") : error?.message || t("js.quick_failed"));
        }
      } finally {
        window.clearTimeout(timeout);
        if (attempt === generation) { controller = null; reset(); }
      }
    });
    const invalidate = () => {
      generation += 1;
      controller?.abort();
      controller = null;
      reset();
    };
    window.addEventListener("pagehide", invalidate);
    window.addEventListener("pageshow", (event) => { if (event.persisted) invalidate(); });
    renderReview();
  }

  function init() {
    const messages = { ...readMessages("ui-translations"), ...readMessages("workspace-translations") };
    initNavigation();
    document.querySelectorAll("[data-download-form]").forEach((form) => initDownloadForm(form, messages));
    if (!window.bootstrap?.Toast) {
      document.querySelectorAll("[data-app-toast]").forEach((toast) => toast.classList.add("show"));
      document.addEventListener("click", (event) => {
        event.target.closest('[data-bs-dismiss="toast"]')?.closest(".toast")?.remove();
      });
    }
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { parseUrls, validMediaUrl, translate, REQUEST_TIMEOUT_MS };
  }
  if (typeof document !== "undefined") init();
})();
