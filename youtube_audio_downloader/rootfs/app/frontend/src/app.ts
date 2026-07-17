import { LitElement, css, html, nothing } from "lit";
import { customElement, state } from "lit/decorators.js";
import { ApiError, apiUrl, request } from "./api";
import { detectLanguage, translate, type Language, type MessageKey } from "./i18n";
import type { HistoryPage, Info, Job, Status } from "./models";
import { parseYouTubeUrlLines } from "./validation";

@customElement("youtube-audio-app")
export class YouTubeAudioApp extends LitElement {
  @state() private language: Language = detectLanguage();
  @state() private status: Status = { state: "idle", progress: 0, queue_length: 0, current: null };
  @state() private queued: Job[] = [];
  @state() private history: HistoryPage = { items: [], page: 1, page_size: 25, total: 0 };
  @state() private info: Info | null = null;
  @state() private url = "";
  @state() private busy = false;
  @state() private error = "";
  @state() private notice = "";
  @state() private historyState = "";
  @state() private confirmClear = false;
  private events?: EventSource;
  private poll?: number;
  private refreshTimer?: number;

  static styles = css`
    :host {
      --app-primary: var(--primary-color, #03a9f4);
      --app-text: var(--primary-text-color, #212121);
      --app-secondary: var(--secondary-text-color, #616161);
      --app-surface: var(--card-background-color, #fff);
      --app-bg: var(--primary-background-color, #f6f6f6);
      --app-divider: var(--divider-color, #dedede);
      display: block; min-height: 100vh; color: var(--app-text); background: var(--app-bg);
      font: 400 14px/1.45 Roboto, system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    main { max-width: 1040px; margin: 0 auto; padding: 20px; }
    header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
    header .titles { flex: 1; min-width: 0; }
    h1 { font-size: 24px; margin: 0; font-weight: 500; }
    h2 { font-size: 18px; margin: 0 0 16px; font-weight: 500; }
    h3 { font-size: 16px; margin: 0 0 4px; font-weight: 500; }
    p { margin: 4px 0; color: var(--app-secondary); }
    .card { background: var(--app-surface); border-radius: 12px; padding: 20px; margin-bottom: 16px;
      box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgb(0 0 0 / 14%)); }
    .add-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: end; }
    wa-input, wa-textarea { width: 100%; }
    wa-button::part(base) { min-height: 44px; }
    .status-pill { border-radius: 999px; padding: 5px 10px; background: color-mix(in srgb, var(--app-primary) 15%, transparent); }
    .error { color: var(--error-color, #db4437); margin-top: 10px; }
    .success { color: var(--success-color, #0f9d58); }
    .job { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; gap: 14px; align-items: center;
      padding: 12px 0; border-top: 1px solid var(--app-divider); }
    .job:first-child { border-top: 0; }
    .thumb { width: 72px; height: 54px; border-radius: 7px; object-fit: cover; background: var(--app-divider); }
    .thumb.fallback { display: grid; place-items: center; font-size: 22px; }
    .meta { color: var(--app-secondary); font-size: 13px; overflow-wrap: anywhere; }
    .actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
    .progress-row { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
    wa-progress-bar { flex: 1; }
    .toolbar { display: flex; gap: 10px; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .toolbar wa-select { min-width: 180px; }
    .pager { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 12px; }
    dl { display: grid; grid-template-columns: max-content 1fr; gap: 7px 14px; margin: 0; }
    dt { color: var(--app-secondary); } dd { margin: 0; overflow-wrap: anywhere; }
    dialog { color: var(--app-text); background: var(--app-surface); border: 0; border-radius: 12px; padding: 22px;
      max-width: 420px; box-shadow: 0 12px 40px rgb(0 0 0 / 30%); }
    dialog::backdrop { background: rgb(0 0 0 / 45%); }
    button:focus-visible, a:focus-visible { outline: 3px solid var(--app-primary); outline-offset: 2px; }
    @media (max-width: 620px) {
      main { padding: 12px; } header { align-items: flex-start; flex-wrap: wrap; }
      .add-form { grid-template-columns: 1fr; }
      .job { grid-template-columns: 56px minmax(0, 1fr); }
      .thumb { width: 56px; height: 48px; }
      .job .actions { grid-column: 1 / -1; }
      .toolbar { align-items: stretch; flex-direction: column; }
      .toolbar wa-select { width: 100%; }
      dl { grid-template-columns: 1fr; gap: 2px; } dd { margin-bottom: 8px; }
    }
    @media (prefers-color-scheme: dark) {
      :host { --app-text: var(--primary-text-color, #e1e1e1); --app-secondary: var(--secondary-text-color, #aaa);
        --app-surface: var(--card-background-color, #242424); --app-bg: var(--primary-background-color, #111);
        --app-divider: var(--divider-color, #444); }
    }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; animation: none !important; } }
  `;

  connectedCallback(): void {
    super.connectedCallback();
    void this.refresh();
    this.connectEvents();
  }

  disconnectedCallback(): void {
    this.events?.close();
    if (this.poll) window.clearInterval(this.poll);
    if (this.refreshTimer) window.clearTimeout(this.refreshTimer);
    super.disconnectedCallback();
  }

  private t(key: MessageKey): string { return translate(this.language, key); }

  private async refresh(): Promise<void> {
    try {
      const stateQuery = this.historyState ? `&state=${this.historyState}` : "";
      const [status, queue, history, info] = await Promise.all([
        request<Status>("v1/status"),
        request<{ items: Job[] }>("v1/queue"),
        request<HistoryPage>(`v1/history?page=${this.history.page}&page_size=25${stateQuery}`),
        request<Info>("v1/info"),
      ]);
      this.status = status; this.queued = queue.items.filter((job) => job.state === "queued");
      this.history = history; this.info = info;
    } catch (error) { this.error = error instanceof Error ? error.message : String(error); }
  }

  private connectEvents(): void {
    this.events = new EventSource(apiUrl("v1/events"));
    const update = (): void => {
      if (this.refreshTimer) return;
      this.refreshTimer = window.setTimeout(() => { this.refreshTimer = undefined; void this.refresh(); }, 250);
    };
    const updateCurrent = (event: MessageEvent<string>): void => {
      try {
        const payload = JSON.parse(event.data) as { job?: Job };
        if (payload.job && payload.job.id === this.status.current?.id) {
          this.status = {
            ...this.status,
            state: payload.job.state,
            progress: payload.job.progress ?? 0,
            current: payload.job,
          };
        }
      } catch { /* A snapshot refresh below remains the safe fallback. */ }
      update();
    };
    this.events.addEventListener("job_updated", updateCurrent as EventListener);
    for (const type of ["status", "queue_changed", "job_completed", "job_failed", "history_changed"])
      this.events.addEventListener(type, update);
    this.events.onerror = () => {
      if (!this.poll) this.poll = window.setInterval(() => void this.refresh(), 10_000);
    };
    this.events.onopen = () => { if (this.poll) { window.clearInterval(this.poll); this.poll = undefined; } };
  }

  private async addJobs(event: Event): Promise<void> {
    event.preventDefault(); this.error = ""; this.notice = "";
    const urls = parseYouTubeUrlLines(this.url);
    if (!urls) { this.error = this.t("invalidUrl"); return; }
    this.busy = true;
    try {
      await request("v1/downloads/batch", { method: "POST", body: JSON.stringify({ urls }) });
      this.notice = this.t("addedToQueue").replace("{count}", String(urls.length));
      this.url = ""; await this.refresh();
    } catch (error) { this.error = error instanceof ApiError ? error.message : String(error); }
    finally { this.busy = false; }
  }

  private async removeQueued(id: string): Promise<void> { await request(`v1/queue/${id}`, { method: "DELETE" }); await this.refresh(); }
  private async cancel(id: string): Promise<void> { await request(`v1/downloads/${id}/cancel`, { method: "POST" }); }
  private async removeHistory(id: string): Promise<void> { await request(`v1/history/${id}`, { method: "DELETE" }); await this.refresh(); }
  private async clearHistory(): Promise<void> { await request("v1/history", { method: "DELETE", body: JSON.stringify({ confirm: true }) }); this.confirmClear = false; await this.refresh(); }
  private formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat(this.language, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—"; }
  private formatBytes(value: number | null): string { return value == null ? "—" : new Intl.NumberFormat(this.language, { style: "unit", unit: value >= 1e9 ? "gigabyte" : "megabyte", maximumFractionDigits: 1 }).format(value / (value >= 1e9 ? 1e9 : 1e6)); }
  private stateLabel(state: Job["state"] | string): string { return this.t((state in { queued: 1, extracting_metadata: 1, downloading: 1, processing: 1, embedding_metadata: 1, completed: 1, failed: 1, cancelled: 1 } ? state : "error") as MessageKey); }

  private thumbnail(job: Job) { return job.thumbnail_url ? html`<img class="thumb" src=${job.thumbnail_url} alt="" loading="lazy" referrerpolicy="no-referrer" />` : html`<div class="thumb fallback" aria-hidden="true">♫</div>`; }

  private renderCurrent() {
    const job = this.status.current;
    return html`<section class="card" aria-labelledby="current-title"><h2 id="current-title">${this.t("current")}</h2>
      ${!job ? html`<p>${this.t("idle")}</p>` : html`<div class="job">${this.thumbnail(job)}<div><h3>${job.title ?? job.url}</h3><p>${job.artist ?? job.channel ?? this.stateLabel(job.state)}</p>
        <div class="progress-row"><wa-progress-bar role="progressbar" aria-label=${this.stateLabel(job.state)} aria-valuemin="0" aria-valuemax="100" aria-valuenow=${job.progress ?? nothing} value=${job.progress ?? nothing}></wa-progress-bar><strong>${job.progress == null ? "…" : `${job.progress.toFixed(1)}%`}</strong></div>
        <p class="meta current-state">${this.stateLabel(job.state)}</p></div>
        <div class="actions"><wa-button variant="danger" @click=${() => void this.cancel(job.id)}>${this.t("cancel")}</wa-button></div></div>`}</section>`;
  }

  private renderQueue() { return html`<section class="card" aria-labelledby="queue-title"><h2 id="queue-title">${this.t("queue")} (${this.queued.length})</h2>
    ${this.queued.length === 0 ? html`<p>${this.t("queueEmpty")}</p>` : this.queued.map((job, index) => html`<div class="job">${this.thumbnail(job)}<div><h3>${index + 1}. ${job.title ?? job.url}</h3><p>${job.artist ?? job.channel ?? this.stateLabel(job.state)}</p><p class="meta">${this.t("added")}: ${this.formatDate(job.created_at)}</p></div><div class="actions"><wa-button @click=${() => void this.removeQueued(job.id)}>${this.t("remove")}</wa-button></div></div>`)}</section>`; }

  private renderHistory() { const pages = Math.max(1, Math.ceil(this.history.total / this.history.page_size)); return html`<section class="card" aria-labelledby="history-title"><div class="toolbar"><h2 id="history-title">${this.t("history")}</h2><div class="actions"><wa-select aria-label="Filter history" value=${this.historyState} @change=${(event: Event) => { this.historyState = (event.target as HTMLSelectElement).value; this.history = { ...this.history, page: 1 }; void this.refresh(); }}><wa-option value="">${this.t("all")}</wa-option><wa-option value="completed">${this.t("completed")}</wa-option><wa-option value="failed">${this.t("failed")}</wa-option><wa-option value="cancelled">${this.t("cancelled")}</wa-option></wa-select><wa-button @click=${() => { this.confirmClear = true; }}>${this.t("clearHistory")}</wa-button></div></div>
    ${this.history.items.length === 0 ? html`<p>${this.t("historyEmpty")}</p>` : this.history.items.map((job) => html`<div class="job">${this.thumbnail(job)}<div><h3>${job.title ?? job.url}</h3><p class=${job.state === "completed" ? "success" : job.state === "failed" ? "error" : ""}>${this.stateLabel(job.state)}${job.artist || job.channel ? ` · ${job.artist ?? job.channel}` : ""}</p><p class="meta">${this.t("finished")}: ${this.formatDate(job.finished_at)} · ${this.formatBytes(job.file_size)}${job.output_file ? ` · ${job.output_file}` : ""}</p>${job.error_message ? html`<p class="error">${job.error_code}: ${job.error_message}</p>` : nothing}</div><div class="actions"><wa-button @click=${() => void this.removeHistory(job.id)}>${this.t("remove")}</wa-button></div></div>`)}
    <div class="pager"><wa-button ?disabled=${this.history.page <= 1} @click=${() => { this.history = { ...this.history, page: this.history.page - 1 }; void this.refresh(); }}>${this.t("previous")}</wa-button><span>${this.history.page} / ${pages}</span><wa-button ?disabled=${this.history.page >= pages} @click=${() => { this.history = { ...this.history, page: this.history.page + 1 }; void this.refresh(); }}>${this.t("next")}</wa-button></div></section>`; }

  render() { return html`<main><header><div class="titles"><h1>${this.t("title")}</h1><p>${this.t("subtitle")}</p></div><span class="status-pill" aria-live="polite">${this.stateLabel(this.status.state)}</span><wa-button aria-label=${this.t("refresh")} @click=${() => void this.refresh()}>↻ ${this.t("refresh")}</wa-button></header>
    <section class="card"><form class="add-form" @submit=${this.addJobs}><wa-textarea label=${this.t("placeholder")} help-text=${this.t("inputHelp")} rows="3" resize="auto" .value=${this.url} @input=${(event: Event) => { this.url = (event.target as HTMLTextAreaElement).value; }} required></wa-textarea><wa-button type="submit" variant="brand" ?loading=${this.busy} ?disabled=${this.busy}>${this.t("add")}</wa-button></form><p>${this.t("sourceQuality")}</p>${this.notice ? html`<p class="success" role="status">${this.notice}</p>` : nothing}${this.error ? html`<p class="error" role="alert">${this.error}</p>` : nothing}</section>
    ${this.renderCurrent()}${this.renderQueue()}${this.renderHistory()}
    <section class="card"><h2>${this.t("about")}</h2>${this.info ? html`<dl><dt>App</dt><dd>${this.info.version}</dd><dt>yt-dlp</dt><dd>${this.info.yt_dlp_version}</dd><dt>ffmpeg</dt><dd>${this.info.ffmpeg_version}</dd><dt>Architecture</dt><dd>${this.info.architecture}</dd><dt>Media</dt><dd>/media/${this.info.output_directory}</dd><dt>Database</dt><dd>${this.info.database}</dd></dl>` : nothing}<p>${this.t("directWarning")}</p></section>
    <dialog ?open=${this.confirmClear} aria-labelledby="clear-title"><h2 id="clear-title">${this.t("clearHistory")}</h2><p>${this.t("clearPrompt")}</p><div class="actions"><wa-button @click=${() => { this.confirmClear = false; }}>${this.t("dismiss")}</wa-button><wa-button variant="danger" @click=${() => void this.clearHistory()}>${this.t("confirm")}</wa-button></div></dialog>
    <div aria-live="polite" class="meta">${this.status.current ? this.stateLabel(this.status.current.state) : ""}</div></main>`; }
}

declare global { interface HTMLElementTagNameMap { "youtube-audio-app": YouTubeAudioApp; } }
