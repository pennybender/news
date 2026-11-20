/* News — phone app. Plain JS, no build step.
   Stories come from data/articles.json (rebuilt by GitHub Actions). What you've read and saved is kept on
   this device (localStorage). If window.NEWS_DEMO is set, that embedded data is used instead. */
(() => {
  "use strict";

  const DEMO = window.NEWS_DEMO || null;
  const $view = document.getElementById("view");
  const PAGE = 40;

  // ---------- device storage (read + saved) ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode etc. */ } },
  };
  const readSet = new Set(store.get("news.read", []));
  let saved = store.get("news.saved", {}); // id -> story (kept even after it drops off the feed)

  const isRead = (a) => readSet.has(a.id) || readSet.has(a.cluster);
  function markRead(a) {
    readSet.add(a.id);
    if (a.cluster) readSet.add(a.cluster);
    store.set("news.read", [...readSet].slice(-5000));
  }
  function toggleSave(a) {
    if (saved[a.id]) delete saved[a.id];
    else saved[a.id] = { ...a };
    store.set("news.saved", saved);
    return !!saved[a.id];
  }

  // ---------- data ----------
  let data = null, byId = new Map(), secMap = {};

  async function load(force = false) {
    if (data && !force) return;
    const raw = DEMO || await fetch("data/articles.json", { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`data ${r.status}`); return r.json();
    });
    const covering = {};
    for (const a of raw.articles) (covering[a.cluster || a.id] ||= new Set()).add(a.source);
    for (const a of raw.articles) {
      a.also_in = [...covering[a.cluster || a.id]].filter((s) => s !== a.source);
      a.minutes = a.words > 400 ? Math.round(a.words / 230) : null;
    }
    data = raw;
    byId = new Map(raw.articles.map((a) => [a.id, a]));
    secMap = Object.fromEntries(raw.sections.map((s) => [s.id, s]));
    // forget read marks for stories that no longer exist
    const live = new Set(raw.articles.flatMap((a) => [a.id, a.cluster]));
    for (const id of readSet) if (!live.has(id)) readSet.delete(id);
    store.set("news.read", [...readSet]);
  }

  const find = (id) => byId.get(id) || saved[id];
  const hoursOld = (iso) => Math.max(0, (Date.now() - new Date(iso)) / 3.6e6);

  function frontPage() {
    const w = (a) => data.sources[a.source]?.weight ?? 1;
    // one card per story: the highest-weighted source's version
    const best = new Map();
    for (const a of data.articles) {
      if (isRead(a) || hoursOld(a.published) > 48) continue;
      const k = a.cluster || a.id, cur = best.get(k);
      if (!cur || w(a) > w(cur)) best.set(k, a);
    }
    const scored = [...best.values()].map((a) => ({
      a,
      score: (secMap[a.section]?.weight ?? 1) * w(a) * Math.exp(-hoursOld(a.published) / 20) * (1 + 0.4 * a.also_in.length),
    })).sort((x, y) => y.score - x.score).map((x) => x.a);

    const { front_page_size: size, max_per_section: cap } = data.settings;
    const lead = [], per = {};
    for (const a of scored) {
      if (lead.length >= size) break;
      if ((per[a.section] || 0) >= cap) continue;
      lead.push(a); per[a.section] = (per[a.section] || 0) + 1;
    }
    const used = new Set(lead.map((a) => a.id));
    const rest = scored.filter((a) => !used.has(a.id));
    const sections = Object.fromEntries(data.sections.map((s) => [s.id, rest.filter((a) => a.section === s.id).slice(0, 4)]));
    return { lead, sections };
  }

  // ---------- rendering helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

  function ago(iso) {
    const mins = Math.max(0, (Date.now() - new Date(iso)) / 60000);
    if (mins < 60) return `${Math.max(1, Math.round(mins))}m`;
    const h = mins / 60;
    if (h < 24) return `${Math.round(h)}h`;
    const d = Math.round(h / 24);
    return d === 1 ? "yesterday" : `${d}d`;
  }

  function meta(a, { showSection = false } = {}) {
    const sec = secMap[a.section];
    const bits = [];
    if (showSection && sec) bits.push(`<span class="kicker" style="--sec:${sec.colour}">${esc(sec.name)}</span>`);
    bits.push(`<span class="src">${esc(a.source)}</span>`);
    if (a.paywalled) bits.push(`<span class="lock" title="Subscriber">🔒</span>`);
    bits.push(`<span class="time-col">${ago(a.published)}</span>`);
    if (a.minutes) bits.push(`<span>${a.minutes} min</span>`);
    if (a.also_in?.length) bits.push(`<span class="also">also in ${esc(a.also_in.join(", "))}</span>`);
    const on = !!saved[a.id];
    return `<div class="meta-row"><div class="meta">${bits.join("<span>·</span>")}</div>
      <button class="save-btn ${on ? "on" : ""}" data-save="${esc(a.id)}" aria-label="${on ? "Unsave" : "Save"}">
        ${on ? "★" : "☆"}</button></div>`;
  }

  function story(a, kind = "compact", opts = {}) {
    const sec = secMap[a.section] || {};
    const kicker = opts.kicker ? `<div class="kicker">${esc(sec.name || "")}</div>` : "";
    const img = kind === "lead" && a.image ? `<img src="${esc(safeUrl(a.image))}" alt="" loading="lazy">` : "";
    const head = kind === "lead" ? "h2" : "h3";
    const summary = opts.summary !== false && a.summary ? `<p>${esc(a.summary)}</p>` : "";
    return `<article class="story ${kind} ${isRead(a) && !opts.ignoreRead ? "read" : ""}" style="--sec:${sec.colour || "var(--accent)"}">
      ${kicker}${img}
      <a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener" data-open="${esc(a.id)}">
        <${head}>${esc(a.title)}</${head}>${summary}</a>
      ${meta(a, opts)}
    </article>`;
  }

  // ---------- views ----------
  function today() {
    const front = frontPage();
    const date = new Date().toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" });
    const [lead, ...rest] = front.lead;
    const failed = data.status.filter((s) => !s.ok).map((s) => s.source);

    let html = `<header class="masthead">
        <div class="dateline"><span>${esc(date)}</span>
          <button class="refresh" id="refresh">${DEMO ? "Sample" : `Updated ${ago(data.generated)} ago`}</button></div>
        <h1>News</h1>
        <div class="tagline">${data.sections.map((s) => esc(s.name.split(" ")[0])).join(" · ")}</div>
        ${DEMO ? `<div class="demo-banner">Preview with made-up sample headlines — the real app fills this from your feeds.</div>` : ""}
      </header>`;

    html += lead
      ? story(lead, "lead", { kicker: true }) + rest.map((a) => story(a, "compact", { kicker: true })).join("")
      : `<div class="empty">Nothing new right now.<br>You're all caught up.</div>`;

    for (const s of data.sections) {
      const items = front.sections[s.id] || [];
      if (!items.length) continue;
      html += `<section class="section-block" style="--sec:${s.colour}">
        <div class="section-head"><h4>${esc(s.name)}</h4>
          <button class="more" data-more="${esc(s.id)}">More →</button></div>
        ${items.map((a) => story(a, "compact", { summary: false })).join("")}
      </section>`;
    }
    html += `<div class="endmark">That's today's paper</div>`;
    if (failed.length && !DEMO) html += `<p class="status-note">Didn't update this time: ${esc(failed.join(", "))}</p>`;
    $view.innerHTML = html;
  }

  let riverSection = null, riverCount = PAGE;
  function river() {
    const all = data.articles.filter((a) => !riverSection || a.section === riverSection);
    const items = all.slice(0, riverCount);
    const chips = [`<button class="chip ${!riverSection ? "active" : ""}" data-chip="">All</button>`]
      .concat(data.sections.map((s) =>
        `<button class="chip ${riverSection === s.id ? "active" : ""}" data-chip="${esc(s.id)}">${esc(s.name)}</button>`));
    $view.innerHTML = `<h2 class="page-title">Latest</h2>
      <p class="page-sub">Everything, newest first.</p>
      <div class="chips">${chips.join("")}</div>
      <div class="list">${items.map((a) => story(a, "compact", { showSection: !riverSection })).join("") ||
        `<div class="empty">No stories yet.</div>`}</div>
      ${all.length > items.length ? `<button class="load-more" id="more">Load more</button>` : ""}`;
  }

  function longReads() {
    const items = data.articles.filter((a) => (a.long_read || a.words > 2000) && !isRead(a)).slice(0, 30);
    $view.innerHTML = `<h2 class="page-title">Long reads</h2>
      <p class="page-sub">Essays and features for when you have time.</p>
      ${items.map((a) => story(a, "longread", { kicker: true })).join("") ||
        `<div class="empty">No long reads waiting.</div>`}`;
  }

  function savedView() {
    const items = Object.values(saved).sort((a, b) => (a.published < b.published ? 1 : -1));
    $view.innerHTML = `<h2 class="page-title">Saved</h2>
      <p class="page-sub">Kept on this phone. Tap ☆ on any story to add it.</p>
      ${items.map((a) => story(a, "compact", { showSection: true, ignoreRead: true })).join("") ||
        `<div class="empty">Nothing saved yet.</div>`}`;
  }

  // ---------- reader view ----------
  const $reader = document.getElementById("reader");
  const textCache = new Map();

  async function getText(id) {
    if (DEMO) return window.NEWS_DEMO_TEXTS?.[id] || "";
    if (!textCache.has(id)) {
      const r = await fetch(`data/a/${id}.json`);
      if (!r.ok) throw new Error(`text ${r.status}`);
      textCache.set(id, (await r.json()).html);
    }
    return textCache.get(id);
  }

  async function openReader(id) {
    await load();
    const a = find(id);
    if (!a) { closeReader(); return; }
    const sec = secMap[a.section] || {};
    const on = !!saved[a.id];
    $reader.innerHTML = `<div class="reader-bar">
        <button class="rb-back" data-close aria-label="Back">‹ Back</button>
        <span class="rb-spacer"></span>
        <button class="save-btn ${on ? "on" : ""}" data-save="${esc(a.id)}" aria-label="Save">${on ? "★" : "☆"}</button>
        <a class="rb-orig" href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener">Original ↗</a>
      </div>
      <article class="reader-body" style="--sec:${sec.colour || "var(--accent)"}">
        <div class="kicker">${esc(sec.name || "")}</div>
        <h1>${esc(a.title)}</h1>
        <div class="reader-meta"><span class="src">${esc(a.source)}</span>${a.author ? ` · ${esc(a.author)}` : ""}
          · ${ago(a.published)}${a.minutes ? ` · ${a.minutes} min read` : ""}</div>
        <div class="reader-text"><p class="loading">Loading…</p></div>
        <a class="reader-end" href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener">Read on ${esc(a.source)} ↗</a>
      </article>`;
    $reader.hidden = false;
    $reader.scrollTop = 0;
    document.body.classList.add("reading");
    markRead(a);
    try {
      $reader.querySelector(".reader-text").innerHTML = await getText(a.id) ||
        `<p>${esc(a.summary)}</p>`;
    } catch {
      $reader.querySelector(".reader-text").innerHTML = `<p>${esc(a.summary)}</p>
        <p class="loading">The full text isn't available offline.</p>`;
    }
    // links inside the article open in Safari
    $reader.querySelectorAll(".reader-text a").forEach((l) => { l.target = "_blank"; l.rel = "noopener"; });
  }

  function closeReader() {
    $reader.hidden = true;
    $reader.innerHTML = "";
    document.body.classList.remove("reading");
  }

  function routeHash() {
    const m = location.hash.match(/^#read-([a-f0-9]+)$/);
    if (m) openReader(m[1]); else if (!$reader.hidden) closeReader();
  }
  window.addEventListener("hashchange", routeHash);

  $reader.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) {
      if (history.length > 1 && location.hash) history.back(); else { location.hash = ""; closeReader(); }
      return;
    }
    const save = e.target.closest("[data-save]");
    if (save) {
      const a = find(save.dataset.save);
      if (!a) return;
      const on = toggleSave(a);
      save.classList.toggle("on", on);
      save.textContent = on ? "★" : "☆";
      document.querySelectorAll(`#view [data-save="${CSS.escape(a.id)}"]`).forEach((b) => {
        b.classList.toggle("on", on); b.textContent = on ? "★" : "☆";
      });
    }
  });

  // ---------- search ----------
  let searchIndex = null, searchQuery = "";

  async function loadIndex() {
    if (searchIndex) return searchIndex;
    if (DEMO) return (searchIndex = window.NEWS_DEMO_INDEX || {});
    try {
      const r = await fetch("data/search.json", { cache: "no-cache" });
      searchIndex = r.ok ? await r.json() : {};
    } catch { searchIndex = {}; }
    return searchIndex;
  }

  const norm = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");

  function runSearch(q) {
    const terms = norm(q).split(/\s+/).filter((t) => t.length > 1);
    if (!terms.length) return [];
    const pool = new Map(data.articles.map((a) => [a.id, a]));
    for (const a of Object.values(saved)) if (!pool.has(a.id)) pool.set(a.id, a);
    const results = [];
    for (const a of pool.values()) {
      const title = norm(a.title), summary = norm(a.summary);
      const meta = norm(`${a.source} ${secMap[a.section]?.name || ""} ${a.author || ""}`);
      const body = searchIndex?.[a.id] ? " " + searchIndex[a.id] : "";
      let score = 0, inBody = false, ok = true;
      for (const t of terms) {
        if (title.includes(t)) score += 6;
        else if (summary.includes(t)) score += 3;
        else if (meta.includes(t)) score += 2;
        else if (body.includes(" " + t)) { score += 1; inBody = true; }
        else { ok = false; break; }
      }
      if (!ok) continue;
      score += Math.max(0, 2 - hoursOld(a.published) / 72); // slight nudge to recent
      results.push({ a, score, inBody });
    }
    return results.sort((x, y) => y.score - x.score).slice(0, 60);
  }

  function searchResults() {
    const box = $view.querySelector(".search-results");
    if (!box) return;
    const q = searchQuery.trim();
    if (!q) {
      box.innerHTML = `<p class="page-sub">Searches headlines, summaries and the full text of stories in the paper (and your saves).</p>`;
      return;
    }
    const hits = runSearch(q);
    const enc = encodeURIComponent(q);
    const elsewhere = `<div class="elsewhere"><div class="kicker">Search elsewhere</div>
        <a href="https://arxiv.org/search/?query=${enc}&searchtype=all" target="_blank" rel="noopener">arXiv ↗</a>
        <a href="https://scholar.google.com/scholar?q=${enc}" target="_blank" rel="noopener">Google Scholar ↗</a>
        <a href="https://duckduckgo.com/?q=${enc}" target="_blank" rel="noopener">Web ↗</a></div>`;
    box.innerHTML = (hits.length
      ? `<p class="page-sub">${hits.length} ${hits.length === 1 ? "story" : "stories"}</p>` +
        hits.map(({ a, inBody }) => story(a, "compact", { showSection: true, summary: true })
          .replace('<div class="meta-row">', inBody ? '<div class="in-text">Matches in the article text</div><div class="meta-row">' : '<div class="meta-row">')).join("")
      : `<div class="empty">Nothing in the paper matches “${esc(q)}”.</div>`) + elsewhere;
  }

  async function searchView() {
    $view.innerHTML = `<h2 class="page-title">Search</h2>
      <form class="search-form" role="search">
        <input type="search" id="q" placeholder="Topic, paper, author, source…" autocomplete="off"
          autocapitalize="off" spellcheck="false" enterkeyhint="search" value="${esc(searchQuery)}">
      </form>
      <div class="search-results"></div>`;
    const input = $view.querySelector("#q");
    $view.querySelector(".search-form").addEventListener("submit", (e) => { e.preventDefault(); input.blur(); });
    let t;
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(() => { searchQuery = input.value; searchResults(); }, 150);
    });
    searchResults();
    if (!searchQuery) input.focus();
    await loadIndex();
    searchResults(); // again, now that article text is searchable too
  }

  const VIEWS = { today, river, long: longReads, search: searchView, saved: savedView };
  let current = "today";

  async function show(name, { force = false, keepScroll = false } = {}) {
    current = name;
    document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    try {
      await load(force);
      VIEWS[name]();
    } catch (e) {
      $view.innerHTML = `<div class="empty">Couldn't load the news.<br><small>${esc(e.message)}</small></div>`;
    }
    if (!keepScroll) window.scrollTo(0, 0);
  }

  // ---------- events ----------
  document.querySelector(".tabbar").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]");
    if (b) { if (b.dataset.view === "river") riverCount = PAGE; show(b.dataset.view); }
  });

  $view.addEventListener("click", (e) => {
    const save = e.target.closest("[data-save]");
    if (save) {
      e.preventDefault();
      const a = find(save.dataset.save);
      if (!a) return;
      const on = toggleSave(a);
      save.classList.toggle("on", on);
      save.textContent = on ? "★" : "☆";
      if (current === "saved" && !on) save.closest(".story").remove();
      return;
    }
    const open = e.target.closest("[data-open]");
    if (open) {
      const a = find(open.dataset.open);
      if (a?.has_text) { e.preventDefault(); location.hash = "read-" + a.id; }
      else if (DEMO) e.preventDefault(); // sample links go nowhere useful
      if (a) markRead(a);
      if (current !== "saved") open.closest(".story").classList.add("read");
      return;
    }
    const more = e.target.closest("[data-more]");
    if (more) { riverSection = more.dataset.more; riverCount = PAGE; show("river"); return; }
    const chip = e.target.closest("[data-chip]");
    if (chip) { riverSection = chip.dataset.chip || null; riverCount = PAGE; river(); return; }
    if (e.target.closest("#more")) { riverCount += PAGE; river(); return; }
    const refresh = e.target.closest("#refresh");
    if (refresh && !DEMO) { refresh.classList.add("spin"); refresh.textContent = "Checking"; show("today", { force: true }); }
  });

  // Coming back to the app after a while: reload the paper
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) hiddenAt = Date.now();
    else if (Date.now() - hiddenAt > 15 * 60 * 1000) show(current, { force: true, keepScroll: current !== "today" });
  });

  if (!DEMO && "serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  show("today").then(routeHash);
})();
