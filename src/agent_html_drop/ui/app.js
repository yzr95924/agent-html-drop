/* agent-html-drop management page.
 *
 * Read-only: lists files via GET /api/files (no auth — public metadata for
 * a docroot nginx already serves unauthenticated at /files/*). No delete /
 * upload buttons — those go through agent MCP, see README.
 *
 * Talks to /api/files with no credential header. All errors surface as
 * a toast.
 */
(function () {
  "use strict";

  // --- DOM refs ----------------------------------------------------------
  var $tbody = document.getElementById("file-tbody");
  var $empty = document.getElementById("empty-state");
  var $loadError = document.getElementById("load-error");
  var $table = document.getElementById("file-table");
  var $previewSection = document.getElementById("preview-section");
  var $previewName = document.getElementById("preview-name");
  var $previewFrame = document.getElementById("preview-frame");
  var $toast = document.getElementById("toast");

  // Iframe must allow same-origin so we can DOM-walk its content for
  // annotation highlighting. The HTML markup sets sandbox="allow-same-origin";
  // we enforce it here as well in case the markup drifts.
  $previewFrame.setAttribute("sandbox", "allow-same-origin");

  // --- helpers -----------------------------------------------------------

  function toast(msg, isError) {
    $toast.textContent = msg;
    $toast.style.borderColor = isError ? "var(--danger)" : "var(--border)";
    $toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { $toast.hidden = true; }, 2500);
  }

  function api(method, path) {
    // No credential header — list is public. A 401 here would mean the
    // daemon is an older build that still requires a token; surface a
    // version-mismatch hint instead of asking for one (we deliberately
    // don't show a token input any more).
    var headers = { "Content-Type": "application/json" };
    return fetch(path, { method: method, headers: headers })
      .then(function (r) {
        if (r.status === 401) {
          toast("daemon 版本不匹配，请升级 agent-html-drop", true);
          throw new Error("unauthorized");
        }
        if (!r.ok) {
          return r.json().then(function (j) {
            toast(j.message || (method + " " + path + " 失败"), true);
            throw new Error(j.error || "http_" + r.status);
          });
        }
        return r.json();
      });
  }

  function fmtSize(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }

  // Absolute timestamp — used as the title (tooltip) for relative time.
  function fmtTimeAbs(unix) {
    var d = new Date(unix * 1000);
    var pad = function (n) { return n < 10 ? "0" + n : n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
      + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  // Relative timestamp — falls back to absolute for anything > 30 days.
  // Locale-free so it matches the rest of the UI (zh-CN dates are scattered
  // around in Chinese; mixing English "minutes ago" would feel inconsistent).
  function fmtTimeRel(unix) {
    var now = Math.floor(Date.now() / 1000);
    var delta = now - unix;
    if (delta < 0) return fmtTimeAbs(unix); // clock skew — show absolute
    if (delta < 60) return "刚刚";
    if (delta < 3600) return Math.floor(delta / 60) + " 分钟前";
    if (delta < 86400) return Math.floor(delta / 3600) + " 小时前";
    if (delta < 30 * 86400) return Math.floor(delta / 86400) + " 天前";
    return fmtTimeAbs(unix);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  // --- actions ------------------------------------------------------------

  function loadFiles() {
    $loadError.hidden = true;
    api("GET", "/api/files").then(function (data) {
      var files = data.files || [];
      $tbody.innerHTML = "";
      if (!files.length) {
        $empty.hidden = false;
        $table.hidden = true;
        return;
      }
      $empty.hidden = true;
      $table.hidden = false;
      files.forEach(function (f) {
        var tr = document.createElement("tr");
        tr.setAttribute("data-name", f.name);
        tr.setAttribute("tabindex", "0");
        tr.setAttribute("role", "button");
        tr.setAttribute("aria-label", "预览 " + f.name);

        // Name (clickable anchor for keyboard / right-click "open in new tab";
        // row click is the primary action). Title is a dim parenthetical.
        var tdName = document.createElement("td");
        var nameLink = document.createElement("a");
        nameLink.href = "#";
        nameLink.setAttribute("data-name", f.name);
        nameLink.textContent = f.name;
        tdName.appendChild(nameLink);
        if (f.title) {
          tdName.appendChild(document.createTextNode(" "));
          var sub = document.createElement("span");
          sub.className = "row-title";
          sub.textContent = "(" + f.title + ")";
          tdName.appendChild(sub);
        }

        var tdSize = document.createElement("td");
        tdSize.textContent = fmtSize(f.size);

        var tdTime = document.createElement("td");
        tdTime.textContent = fmtTimeRel(f.mtime);
        tdTime.title = fmtTimeAbs(f.mtime);

        // Annotation count — clicking jumps to anno mode + opens the file.
        // 0 = no link (greyed). Anything else is a button-style link.
        var tdAnno = document.createElement("td");
        if (f.annotation_count > 0) {
          var annoLink = document.createElement("a");
          annoLink.href = "#";
          annoLink.className = "anno-count";
          annoLink.setAttribute("data-name", f.name);
          annoLink.textContent = f.annotation_count + " 条";
          tdAnno.appendChild(annoLink);
        } else {
          tdAnno.textContent = "—";
          tdAnno.className = "row-dim";
        }

        // Copy-URL action — small button, inline with the row.
        var tdActions = document.createElement("td");
        var copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "row-action";
        copyBtn.textContent = "复制 URL";
        copyBtn.title = f.url;
        copyBtn.setAttribute("aria-label", "复制 " + f.name + " 公开 URL");
        copyBtn.onclick = function (ev) {
          ev.stopPropagation();   // don't bubble to row preview
          copyUrl(f.url);
        };
        tdActions.appendChild(copyBtn);

        tr.appendChild(tdName);
        tr.appendChild(tdSize);
        tr.appendChild(tdTime);
        tr.appendChild(tdAnno);
        tr.appendChild(tdActions);
        $tbody.appendChild(tr);
      });
      // Restore last-opened file if it's still in the list. This runs
      // once at page load — preview() captures the new scroll position,
      // and the iframe `load` handler restores the saved Y. Without this
      // the user has to click the file again on every reload, which
      // defeats "I was reading this yesterday" continuity.
      var last = lsStr(LS_LAST_FILE, "");
      if (last && files.some(function (f) { return f.name === last; })) {
        preview(last);
      }
    }).catch(function (err) {
      // api() already toasted; also surface an inline error in the table
      // area so the user can see "list failed to load" even after the
      // toast disappears (toast = transient, inline = state).
      $tbody.innerHTML = "";
      $table.hidden = true;
      $empty.hidden = true;
      $loadError.textContent =
        "加载文件列表失败：" + (err && err.message ? err.message : "网络错误");
      $loadError.hidden = false;
    });
  }

  function preview(name) {
    $previewSection.hidden = false;
    $previewName.textContent = "(" + name + ")";
    $previewFrame.src = "/files/" + encodeURIComponent(name);
    // Remember which file the user opened last so a reload can put them
    // back. The scroll position is restored separately, after the iframe
    // loads (see onIframeLoad below) — it depends on the new document
    // having a measurable scrollHeight.
    lsSetStr(LS_LAST_FILE, name);
    lsSetNumber(LS_LAST_SCROLL, 0);   // reset on file switch
    // Scroll the preview into view. Without this, on a viewport where
    // the file table fills the fold, clicking a filename reveals the
    // iframe but the user has to manually scroll down to see it — the
    // hidden→visible transition is meaningless if it's offscreen.
    // Defer to next tick so the unhide + iframe src change settle first.
    setTimeout(function () {
      $previewSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }

  function copyUrl(url) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(
        function () { toast("已复制 URL 到剪贴板"); },
        function () { fallbackCopy(url); }
      );
    } else {
      fallbackCopy(url);
    }
  }

  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      toast("已复制 URL");
    } catch (e) {
      toast("复制失败", true);
    }
    document.body.removeChild(ta);
  }

  // --- wire up ------------------------------------------------------------

  // Click delegation: any row OR any link inside it triggers preview,
  // unless the click came from a row-action button (copy, etc.) which
  // stops propagation. Keyboard support: Enter/Space on a focused row
  // also previews.
  function rowActivate(target) {
    var name = target && target.getAttribute
      && target.getAttribute("data-name");
    if (name) preview(name);
  }

  $tbody.onclick = function (e) {
    var link = e.target.closest("a[data-name]");
    if (link) {
      e.preventDefault();
      rowActivate(link);
      return;
    }
    var tr = e.target.closest("tr[data-name]");
    if (tr) rowActivate(tr);
  };

  $tbody.onkeydown = function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var tr = e.target.closest("tr[data-name]");
    if (!tr) return;
    e.preventDefault();
    rowActivate(tr);
  };

  // --- version chip -----------------------------------------------------
  // The header shows "agent-html-drop 管理 v0.2.3" so the user can see
  // which daemon build they're talking to. The version comes from
  // /api/health (no auth) — that way it always reflects the actual
  // running daemon, not whatever the static HTML was last served from.
  // Silent on failure: missing version is just an empty chip, not a
  // noisy error (the file list failing is the much louder signal).
  (function loadVersionTag() {
    var $tag = document.getElementById("version-tag");
    if (!$tag) return;
    fetch("/api/health").then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (j && j.version) $tag.textContent = "v" + j.version;
      }).catch(function () { /* keep placeholder */ });
  })();

  // Initial load — list is always public; just call.
  loadFiles();

  /* === annotation mode (extension) ============================== */

  // --- state ---------------------------------------------------------
  var mode = "read"; // "read" | "anno"
  var annoCurrentFile = null;
  var annoEntries = [];

  // --- UI-pref persistence (layout only; the token is NEVER persisted) ---
  var LS_ANNO_COLLAPSED = "agent-html-drop:annoCollapsed";
  var LS_TOC_HIDDEN = "agent-html-drop:tocHidden";
  var LS_LAST_FILE = "agent-html-drop:lastFile";
  var LS_LAST_SCROLL = "agent-html-drop:lastScroll";

  function lsBool(key, dflt) {
    try {
      var v = localStorage.getItem(key);
      return v === null ? dflt : v === "1";
    } catch (e) {
      return dflt;
    }
  }
  function lsSetBool(key, val) {
    try { localStorage.setItem(key, val ? "1" : "0"); } catch (e) {}
  }
  function lsStr(key, dflt) {
    try {
      var v = localStorage.getItem(key);
      return v === null ? dflt : v;
    } catch (e) {
      return dflt;
    }
  }
  function lsSetStr(key, val) {
    try { localStorage.setItem(key, String(val)); } catch (e) {}
  }
  function lsNumber(key, dflt) {
    try {
      var v = localStorage.getItem(key);
      var n = v === null ? NaN : parseInt(v, 10);
      return isNaN(n) ? dflt : n;
    } catch (e) {
      return dflt;
    }
  }
  function lsSetNumber(key, val) {
    try { localStorage.setItem(key, String(Math.floor(val))); } catch (e) {}
  }

  var annoCollapsed = lsBool(LS_ANNO_COLLAPSED, true);
  var tocHidden = lsBool(LS_TOC_HIDDEN, false);

  // --- DOM refs (anno-specific) --------------------------------------
  var $annoToggle = document.getElementById("anno-toggle");
  var $annoModeHint = document.getElementById("anno-mode-hint");
  var $annoExit = document.getElementById("anno-exit");
  var $annoDialog = document.getElementById("anno-token-dialog");
  var $annoForm = document.getElementById("anno-token-form");
  var $annoInput = document.getElementById("anno-token-input");
  var $annoCancel = document.getElementById("anno-token-cancel");
  var $annoError = document.getElementById("anno-token-error");
  var $annoSidebar = document.getElementById("anno-sidebar");
  var $annoList = document.getElementById("anno-list");
  var $annoEmpty = document.getElementById("anno-empty");
  var $annoSidebarRefresh = document.getElementById("anno-sidebar-refresh");
  var $annoSidebarTitle = document.getElementById("anno-sidebar-title");
  var $annoCollapse = document.getElementById("anno-collapse");
  var $annoOpener = document.getElementById("anno-opener");
  var $tocToggle = document.getElementById("toc-toggle");

  // --- helpers -------------------------------------------------------

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  function normalize(s) {
    return String(s).replace(/\s+/g, " ").trim();
  }

  // Build a same-origin URL for the same host as the page (so Origin
  // header matches the iframe's actual host when daemon lives behind nginx).
  function originFor() {
    return window.location.origin;
  }

  function csrfHeaders(extra) {
    var h = { "Content-Type": "application/json", "Origin": originFor() };
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
  }

  function credentials() {
    return "include";
  }

  function setMode(newMode) {
    mode = newMode;
    hidePreviewPopover();
    if (mode === "anno") {
      $annoToggle.hidden = true;
      $annoModeHint.hidden = false;
      // The side panel is anno mode's editing surface — surface it on entry.
      // (Still foldable afterwards; the fold persists like read mode's.)
      setAnnoCollapsed(false);
    } else {
      $annoToggle.hidden = false;
      $annoModeHint.hidden = true;
      pendingQuote = null;
      hideAddFab();
      // Leaving anno mode keeps the file + annotations visible (read-only);
      // re-render so the auth-backed delete buttons drop out.
      renderAnnoList();
      highlightIframe();
    }
    applyAnnoSidebarVisibility();
  }

  // --- annotation panel fold (persisted) -----------------------------
  // Visibility = user wants it open AND there's something to show:
  // a file is previewed AND (anno mode, or it actually has annotations).
  // Read mode with zero annotations stays out of the way.
  function applyAnnoSidebarVisibility() {
    var relevant = !!annoCurrentFile && (mode === "anno" || annoEntries.length > 0);
    // The fold is user-controlled in BOTH modes — anno mode auto-opens the
    // panel on entry (see setMode) since it's the editing surface, but the
    // collapse button is never taken away. While open, the panel PUSHES the
    // page left (body.anno-sidebar-open, see style.css) instead of overlaying
    // it, so the right-edge controls (大纲 toggle, iframe scrollbar, header
    // actions) stay clickable. Comments are also readable via the popover.
    var wantVisible = relevant && !annoCollapsed;
    $annoSidebar.classList.toggle("collapsed", !wantVisible);
    $annoOpener.hidden = !(relevant && !wantVisible);
    document.body.classList.toggle("anno-sidebar-open", wantVisible);
  }

  function setAnnoCollapsed(c) {
    annoCollapsed = c;
    lsSetBool(LS_ANNO_COLLAPSED, c);
    applyAnnoSidebarVisibility();
  }

  function showAnnoError(msg) {
    $annoError.textContent = msg;
    $annoError.hidden = false;
  }
  function clearAnnoError() {
    $annoError.textContent = "";
    $annoError.hidden = true;
  }

  // --- auth flow -----------------------------------------------------

  // --- session probe: skip the token dialog when the HttpOnly cookie is
  //     still valid. The cookie is HttpOnly so JS can't read it; we ask the
  //     server via GET /api/auth (204 = logged in, 401 = prompt for token). ---
  function probeSession(onValid, onInvalid) {
    fetch("/api/auth", { method: "GET", credentials: credentials() })
      .then(function (r) { (r.status === 204 ? onValid : onInvalid)(); })
      .catch(function () { if (onInvalid) onInvalid(); });
  }

  function enterAnnoMode() {
    setMode("anno");
    if (annoCurrentFile) refreshAnnoList();
  }

  function openTokenDialog() {
    clearAnnoError();
    $annoInput.value = "";
    if (typeof $annoDialog.showModal === "function") {
      $annoDialog.showModal();
    } else {
      $annoDialog.setAttribute("open", "");
    }
    $annoInput.focus();
  }

  // Clicking 批注: probe first — if already logged in, skip the token dialog.
  $annoToggle.onclick = function () {
    probeSession(enterAnnoMode, openTokenDialog);
  };

  $annoCancel.onclick = function () { $annoDialog.close(); };

  $annoForm.onsubmit = function (e) {
    e.preventDefault();
    clearAnnoError();
    var token = $annoInput.value.trim();
    if (!token) {
      showAnnoError("请输入 token");
      return;
    }
    fetch("/api/auth", {
      method: "POST",
      credentials: credentials(),
      headers: { "Authorization": "Bearer " + token },
    }).then(function (r) {
      if (r.status === 204) {
        $annoDialog.close();
        setMode("anno");
        // If a file is currently previewed, refresh annotations.
        if (annoCurrentFile) refreshAnnoList();
      } else if (r.status === 401) {
        showAnnoError("token 错误,联系 owner 获取");
      } else {
        showAnnoError("server 错误 " + r.status);
      }
    }).catch(function () {
      showAnnoError("网络错误,稍后重试");
    });
  };

  $annoExit.onclick = function (e) {
    e.preventDefault();
    // No "logout" endpoint; simplest: ask server to forget by sending empty
    // Authorization on a no-op fetch won't work. Instead, client just
    // transitions back to read mode; server-side cookie expires naturally.
    setMode("read");
  };

  $annoSidebarRefresh.onclick = function () { refreshAnnoList(); };

  if ($annoCollapse) $annoCollapse.onclick = function () { setAnnoCollapsed(true); };
  if ($annoOpener) $annoOpener.onclick = function () { setAnnoCollapsed(false); };

  // --- annotations: list / render -----------------------------------

  function refreshAnnoList() {
    if (!annoCurrentFile) return;
    fetch("/api/files/" + encodeURIComponent(annoCurrentFile) + "/annotations", {
      credentials: credentials(),
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        annoEntries = (data && data.annotations) || [];
        renderAnnoList();
        highlightIframe();
      })
      .catch(function () {
        annoEntries = [];
        renderAnnoList();
      });
  }

  function renderAnnoList() {
    $annoList.innerHTML = "";
    $annoSidebarTitle.textContent = "批注 · " + annoCurrentFile;
    applyAnnoSidebarVisibility();
    if (!annoEntries.length) {
      $annoEmpty.hidden = false;
      return;
    }
    $annoEmpty.hidden = true;
    annoEntries.forEach(function (e) {
      var li = document.createElement("li");
      li.setAttribute("data-anno-id", e.id);
      var quote = document.createElement("div");
      quote.className = "quote";
      quote.textContent = '"' + e.quote + '"';
      li.appendChild(quote);
      var comment = document.createElement("div");
      comment.className = "comment";
      comment.textContent = e.comment;
      li.appendChild(comment);
      var meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = e.author + " · " + new Date(e.ts * 1000).toISOString().slice(0, 16).replace("T", " ");
      li.appendChild(meta);
      // Delete is auth-backed (anno session cookie); read mode hides it.
      if (mode === "anno") {
        var actions = document.createElement("div");
        actions.className = "actions";
        var delBtn = document.createElement("button");
        delBtn.className = "danger";
        delBtn.textContent = "删除";
        delBtn.onclick = function () { deleteAnno(e.id); };
        actions.appendChild(delBtn);
        li.appendChild(actions);
      }
      $annoList.appendChild(li);
    });
  }

  function clearAnnoList() {
    $annoList.innerHTML = "";
    annoEntries = [];
    annoCurrentFile = null;
  }

  function deleteAnno(id) {
    if (!annoCurrentFile) return;
    if (!window.confirm("删除这条批注?")) return;
    fetch(
      "/api/files/" + encodeURIComponent(annoCurrentFile) + "/annotations/" + id,
      {
        method: "DELETE",
        credentials: credentials(),
        headers: { "Origin": originFor() },
      }
    ).then(function (r) {
      if (r.status === 200) refreshAnnoList();
      else toast("删除失败 " + r.status, true);
    });
  }

  // --- iframe `<mark>` injection ------------------------------------
  //
  // Document-level text map: concatenate all text nodes, find the
  // (whitespace-normalized) quote in the concatenated text, then map the
  // match back to (node, offset) ranges and wrap each piece in its own
  // <mark>. This highlights quotes that SPAN element boundaries (<b>,
  // paragraphs, …) — the old single-text-node search couldn't.
  //
  // Details:
  // - A synthetic space is inserted in the concatenated text between two
  //   text nodes whose NEAREST BLOCK ancestor differs (p / div / li / td
  //   / …) — mirroring how getSelection().toString() puts newlines at
  //   block boundaries but not at inline ones. (Residual gap: <br> inside
  //   a single block isn't treated as a boundary.)
  // - All occurrences of a quote are located in ONE map pass, then
  //   wrapped RIGHT-TO-LEFT so earlier offsets stay valid (splitText
  //   truncates the original node in place, so a shared node still works).
  // - Text already inside a <mark> is NOT excluded: overlapping
  //   annotations of the same span both highlight (marks nest, valid
  //   HTML) instead of the later one being falsely flagged ⚠️.
  // - Each run first unwraps ALL existing marks (and parent.normalize()
  //   re-merges the split text nodes), so re-highlighting is idempotent:
  //   no progressive nesting on repeat refreshes, and marks of deleted
  //   annotations disappear instead of going stale.

  var BLOCK_RE = /^(P|DIV|H1|H2|H3|H4|H5|H6|LI|DT|DD|TD|TH|TR|TABLE|SECTION|ARTICLE|HEADER|FOOTER|BLOCKQUOTE|PRE|UL|OL|DL|FIGURE|FIGCAPTION|FORM|FIELDSET|NAV|ASIDE|MAIN|HR)$/;

  // Style annotation <mark>s inside the preview iframe. The iframe is a
  // separate document, so the management page's style.css doesn't reach it,
  // and the md→html theme has no `mark` rule — without this, <mark> falls
  // back to the browser-default glaring yellow, which wouldn't match the
  // public page.
  //
  // The CSS text comes from /anno-marks.css (cached after first fetch) —
  // the same file the public-page viewer loads via <link>, so the two
  // surfaces can't drift on color or hover state. (Earlier the contract
  // was a "keep in sync" comment between app.js and anno-viewer.js;
  // now it's the same bytes.)
  var _markStyleText = null;
  function ensureMarkStyle(doc) {
    if (doc.getElementById("ahd-anno-marks")) return;
    var head = doc.head || doc.documentElement;
    if (!head) return;
    if (_markStyleText === null) {
      // Inline fallback (yellow with alpha) so a fetch failure still
      // highlights something instead of leaving raw yellow. The fetch
      // will retry on every subsequent iframe load until it succeeds.
      _markStyleText = "mark[data-anno-id]{background:rgba(255,196,0,.32);border-radius:2px;padding:0 1px;cursor:pointer;}";
      fetch("/anno-marks.css").then(function (r) {
        return r.ok ? r.text() : null;
      }).then(function (txt) {
        if (txt) _markStyleText = txt;
      }).catch(function () {});
    }
    var s = doc.createElement("style");
    s.id = "ahd-anno-marks";
    s.textContent = _markStyleText;
    head.appendChild(s);
  }

  function highlightIframe() {
    if (!$previewFrame || !$previewFrame.contentDocument) return;
    var doc = $previewFrame.contentDocument;
    if (!doc.body) return;
    ensureMarkStyle(doc);
    unwrapMarks(doc);
    annoEntries.forEach(function (e) {
      var found = highlightQuote(doc, e);
      if (!found) {
        var li = $annoList.querySelector('li[data-anno-id="' + cssEscape(e.id) + '"]');
        if (li) li.classList.add("invalid");
      }
    });
    wireIframeMarks(doc);
  }

  function unwrapMarks(doc) {
    // querySelectorAll is a STATIC list — safe to mutate while iterating.
    var marks = doc.querySelectorAll("mark[data-anno-id]");
    for (var i = 0; i < marks.length; i++) {
      var m = marks[i];
      var p = m.parentNode;
      if (!p) continue;
      while (m.firstChild) p.insertBefore(m.firstChild, m);
      p.removeChild(m);
      p.normalize(); // merge text nodes re-adjoined by the unwrap
    }
  }

  // Wrap every occurrence of entry.quote; returns true if at least one
  // was found (drives the sidebar ⚠️ flag).
  function highlightQuote(doc, entry) {
    var quote = normalize(entry.quote);
    if (!quote) return false;
    var map = buildTextMap(doc);
    var matches = [];
    var from = 0;
    while (matches.length < 500) { // 500: cap for pathological tiny quotes
      var idx = map.norm.indexOf(quote, from);
      if (idx < 0) break;
      matches.push(idx);
      from = idx + quote.length; // occurrences never overlap each other
    }
    for (var i = matches.length - 1; i >= 0; i--) {
      wrapRange(doc, map, matches[i], matches[i] + quote.length, entry.id);
    }
    return matches.length > 0;
  }

  // Concatenate text nodes (document order) into one string, plus a
  // whitespace-collapsed variant with a per-char index map back into the
  // raw string.
  function buildTextMap(doc) {
    var walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
    var nodes = [];
    var starts = []; // raw offset where each node's text begins
    var raw = "";
    var prevBlock = null;
    var node;
    while ((node = walker.nextNode())) {
      var block = nearestBlock(node);
      if (prevBlock !== null && block !== prevBlock) {
        raw += " "; // synthetic block-boundary separator (see header note)
      }
      prevBlock = block;
      nodes.push(node);
      starts.push(raw.length);
      raw += node.nodeValue;
    }
    // Collapse \s+ runs to a single space, remembering for every
    // normalized char which raw char it came from. (No trim — offsets
    // must stay aligned; the quote itself is already trimmed.)
    var norm = "";
    var normToRaw = [];
    var inSpace = false;
    for (var i = 0; i < raw.length; i++) {
      if (/\s/.test(raw.charAt(i))) {
        if (!inSpace) {
          norm += " ";
          normToRaw.push(i);
          inSpace = true;
        }
      } else {
        norm += raw.charAt(i);
        normToRaw.push(i);
        inSpace = false;
      }
    }
    return { nodes: nodes, starts: starts, norm: norm, normToRaw: normToRaw };
  }

  function nearestBlock(node) {
    var el = node.parentElement;
    while (el) {
      if (BLOCK_RE.test(el.tagName)) return el;
      el = el.parentElement;
    }
    return null;
  }

  // Wrap the raw-text range corresponding to normalized [nStart, nEnd).
  // The quote starts and ends on non-whitespace (it's trimmed), so both
  // endpoints land on real chars in text nodes (never on a synthetic
  // separator); everything raw between them — collapsed whitespace runs,
  // separators, element boundaries — is spanned by the wrap.
  function wrapRange(doc, map, nStart, nEnd, annoId) {
    var rStart = map.normToRaw[nStart];
    var rEnd = map.normToRaw[nEnd - 1] + 1;
    for (var i = 0; i < map.nodes.length; i++) {
      var node = map.nodes[i];
      var s = map.starts[i];
      var len = node.nodeValue.length;
      if (s + len <= rStart) continue;
      if (s >= rEnd) break;
      var localStart = Math.max(0, rStart - s);
      var localEnd = Math.min(len, rEnd - s);
      if (localEnd <= localStart) continue;
      // splitText twice isolates [localStart, localEnd) as its own node.
      var middle = node.splitText(localStart);
      middle.splitText(localEnd - localStart);
      var mark = doc.createElement("mark");
      mark.setAttribute("data-anno-id", annoId);
      middle.parentNode.insertBefore(mark, middle);
      mark.appendChild(middle);
    }
  }

  function cssEscape(s) {
    return String(s).replace(/(["\\])/g, "\\$1");
  }

  /* === annotation popover (read a comment without the covering sidebar) ===
   *
   * The sidebar defaults to folded in read mode so it never covers the
   * document; the popover is the primary read UI. It lives in the PARENT
   * document (the marks are inside the same-origin sandboxed iframe) and is
   * positioned over the iframe via iframe-rect + mark-rect — the same
   * coordinate scheme as the add-annotation FAB (§9.3).
   */
  var $annoPopover = document.getElementById("anno-popover");
  var $popQuote = document.getElementById("anno-popover-quote");
  var $popComment = document.getElementById("anno-popover-comment");
  var $popMeta = document.getElementById("anno-popover-meta");
  var popoverCurrent = null;
  var popoverOrderedMarks = [];   // marks in document order, recomputed on highlight

  function entryById(id) {
    for (var i = 0; i < annoEntries.length; i++) {
      if (annoEntries[i].id === id) return annoEntries[i];
    }
    return null;
  }

  function hidePreviewPopover() {
    if ($annoPopover) $annoPopover.hidden = true;
    popoverCurrent = null;
  }

  function showPreviewPopover(entry, left, bottomY, topY, mark) {
    if (!$annoPopover) return;
    if (popoverCurrent === mark) { hidePreviewPopover(); return; }   // toggle
    popoverCurrent = mark;
    $popQuote.textContent = "“" + entry.quote + "”";
    $popComment.textContent = entry.comment;
    $popMeta.textContent = entry.author + " · "
      + new Date(entry.ts * 1000).toISOString().slice(0, 16).replace("T", " ");
    $annoPopover.hidden = false;
    updatePopoverCounter();
    var pw = $annoPopover.offsetWidth, ph = $annoPopover.offsetHeight;
    if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
    if (left < 8) left = 8;
    var top = bottomY + 6;
    if (top + ph > window.innerHeight - 8) top = topY - ph - 6;   // flip above
    if (top < 8) top = 8;
    $annoPopover.style.left = left + "px";
    $annoPopover.style.top = top + "px";
  }

  // Show the popover for a given mark, positioning it next to that
  // mark's location. Used by the prev/next nav buttons to move through
  // marks in document order without having to scroll-find them.
  function showPopoverForMark(mark) {
    if (!mark) return;
    var entry = entryById(mark.getAttribute("data-anno-id"));
    if (!entry) return;
    var mr = mark.getBoundingClientRect();
    var fr = $previewFrame.getBoundingClientRect();
    showPreviewPopover(
      entry,
      fr.left + mr.left,
      fr.top + mr.bottom,
      fr.top + mr.top,
      mark,
    );
  }

  function updatePopoverCounter() {
    var $counter = document.getElementById("anno-popover-counter");
    if (!$counter) return;
    var total = popoverOrderedMarks.length;
    var idx = popoverOrderedMarks.indexOf(popoverCurrent);
    $counter.textContent = total > 0
      ? (idx + 1) + " / " + total
      : "—";
  }

  function navPopover(dir) {
    if (!popoverOrderedMarks.length) return;
    var idx = popoverOrderedMarks.indexOf(popoverCurrent);
    // -1 means popoverCurrent is null or stale; default to first.
    var next = ((idx < 0 ? -1 : idx) + dir + popoverOrderedMarks.length)
      % popoverOrderedMarks.length;
    var target = popoverOrderedMarks[next];
    if (!target) return;
    // Scroll the iframe so the target mark is in view, then place the
    // popover next to it. Without this, next/prev from a distant mark
    // would jump to its position visually but the popover would still
    // hover over the old screen location.
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    // scrollIntoView is animated; wait one frame before measuring the
    // mark's new viewport position. requestAnimationFrame would be nicer
    // but the iframe's smooth scroll finishes on its own timeline.
    setTimeout(function () { showPopoverForMark(target); }, 250);
  }

  function onIframeMarkClick(ev) {
    ev.stopPropagation();   // keep the iframe-doc click-dismiss from firing
    ev.preventDefault();
    var mark = ev.currentTarget;
    var entry = entryById(mark.getAttribute("data-anno-id"));
    if (!entry) return;
    var mr = mark.getBoundingClientRect();
    var fr = $previewFrame.getBoundingClientRect();
    showPreviewPopover(entry, fr.left + mr.left, fr.top + mr.bottom, fr.top + mr.top, mark);
  }

  function wireIframeMarks(doc) {
    var marks = doc.querySelectorAll("mark[data-anno-id]");
    // Snapshot the marks in document order so prev/next navigation
    // matches where they actually appear in the article (not the API
    // insert order, which is the same here but a stale assumption).
    popoverOrderedMarks = Array.prototype.slice.call(marks);
    for (var i = 0; i < marks.length; i++) {
      marks[i].addEventListener("click", onIframeMarkClick);
    }
  }

  if ($annoPopover) {
    // clicks inside the popover (select text, close) must not dismiss it
    $annoPopover.onclick = function (ev) { ev.stopPropagation(); };
    var $popCloseBtn = document.getElementById("anno-popover-close");
    if ($popCloseBtn) $popCloseBtn.onclick = hidePreviewPopover;
    var $popPrev = document.getElementById("anno-popover-prev");
    var $popNext = document.getElementById("anno-popover-next");
    if ($popPrev) $popPrev.onclick = function () { navPopover(-1); };
    if ($popNext) $popNext.onclick = function () { navPopover(1); };
    document.addEventListener("click", function (ev) {
      if (!$annoPopover.hidden && !$annoPopover.contains(ev.target)) hidePreviewPopover();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") hidePreviewPopover();
      // Alt+Left / Alt+Right → prev/next annotation without leaving
      // keyboard for users reading long docs.
      if (ev.altKey && ev.key === "ArrowLeft") { ev.preventDefault(); navPopover(-1); }
      if (ev.altKey && ev.key === "ArrowRight") { ev.preventDefault(); navPopover(1); }
      // Page Up/Down, Home/End, Space → forward to the preview iframe.
      // Without this, keyboard users have to click into the iframe before
      // any of these keys work — the iframe is its own scroll context.
      // File-table keyboard nav uses Enter/Space/Tab/Arrow keys on rows
      // (handled separately via $tbody.onkeydown), which won't conflict:
      // a focused row's Space goes to rowActivate() first; here we only
      // route to the iframe when no row is focused.
      if ($previewFrame && !$previewFrame.hidden && $previewFrame.contentWindow
          && !ev.target.closest("input,textarea,button,tr[data-name]")
          && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        var keys = { "PageDown": 1, "PageUp": -1, "Space": 1 };
        var dir = keys[ev.key];
        if (dir) {
          var w = $previewFrame.contentWindow;
          var h = w.innerHeight || 600;
          w.scrollBy({ top: dir * (h * 0.9), behavior: "auto" });
          ev.preventDefault();
        } else if (ev.key === "Home") {
          $previewFrame.contentWindow.scrollTo(0, 0);
          ev.preventDefault();
        } else if (ev.key === "End") {
          var d = $previewFrame.contentDocument;
          if (d) {
            var h = d.documentElement.scrollHeight;
            $previewFrame.contentWindow.scrollTo(0, h);
            ev.preventDefault();
          }
        }
      }
    });
    window.addEventListener("scroll", hidePreviewPopover, true);
  }

  /* === annotation creation (F22: iframe selection → POST) ==========
   *
   * Flow (design.md S37): in anno mode, user selects text inside the
   * preview iframe → a floating "＋ 批注" button appears next to the
   * selection → click opens a dialog (quote preview + comment textarea)
   * → POST /api/files/<name>/annotations → refresh list + re-highlight.
   *
   * The fab lives in the PARENT document (§9.3 iframe isolation), so its
   * position is computed as iframe-viewport-rect + range-rect, both
   * viewport-relative → position: fixed coordinates line up.
   */

  var MAX_QUOTE_LEN = 200; // mirrors storage/annotations.py _MAX_QUOTE_LEN

  var $annoAddFab = document.getElementById("anno-add-fab");
  var $annoAddDialog = document.getElementById("anno-add-dialog");
  var $annoAddForm = document.getElementById("anno-add-form");
  var $annoAddQuote = document.getElementById("anno-add-quote");
  var $annoAddTruncated = document.getElementById("anno-add-truncated");
  var $annoAddComment = document.getElementById("anno-add-comment");
  var $annoAddCancel = document.getElementById("anno-add-cancel");
  var $annoAddError = document.getElementById("anno-add-error");

  // Quote captured at selectionchange time — clicking the fab may collapse
  // the iframe selection, so we never re-read it at dialog-open time.
  var pendingQuote = null;
  var pendingTruncated = false;

  function iframeSelection() {
    var w = $previewFrame.contentWindow;
    if (!w || !w.getSelection) return null;
    return w.getSelection();
  }

  function hideAddFab() {
    $annoAddFab.hidden = true;
  }

  function showAddFab(rangeRect) {
    var fr = $previewFrame.getBoundingClientRect();
    $annoAddFab.style.left = (fr.left + rangeRect.left) + "px";
    $annoAddFab.style.top = (fr.top + rangeRect.bottom + 6) + "px";
    $annoAddFab.hidden = false;
  }

  function onIframeSelectionChange() {
    if (mode !== "anno" || !annoCurrentFile) {
      pendingQuote = null;
      hideAddFab();
      return;
    }
    var sel = iframeSelection();
    var text = sel && !sel.isCollapsed ? normalize(sel.toString()) : "";
    if (!text || !sel.rangeCount) {
      pendingQuote = null;
      hideAddFab();
      return;
    }
    pendingQuote = text.slice(0, MAX_QUOTE_LEN);
    pendingTruncated = text.length > MAX_QUOTE_LEN;
    showAddFab(sel.getRangeAt(0).getBoundingClientRect());
  }

  // Re-attach on every iframe load: the document (and its listeners) is
  // discarded on navigation.
  function attachSelectionListener() {
    var doc = $previewFrame.contentDocument;
    if (!doc) return;
    doc.addEventListener("selectionchange", onIframeSelectionChange);
    // Scroll invalidates the fab's fixed position; simplest correct
    // behavior is to hide it (selection stays, re-select to re-show).
    doc.addEventListener("scroll", hideAddFab, true);
    // A click that isn't on a mark (marks stopPropagation) dismisses the popover.
    doc.addEventListener("click", hidePreviewPopover);
  }

  function clearIframeSelection() {
    var sel = iframeSelection();
    if (sel) sel.removeAllRanges();
  }

  // mousedown + preventDefault: keep the iframe selection from collapsing
  // before the dialog opens (quote is already captured, this is for UX).
  $annoAddFab.addEventListener("mousedown", function (e) {
    e.preventDefault();
  });

  $annoAddFab.addEventListener("click", function () {
    if (!pendingQuote) return;
    clearAddError();
    $annoAddQuote.textContent = '"' + pendingQuote + '"';
    $annoAddTruncated.hidden = !pendingTruncated;
    $annoAddComment.value = "";
    hideAddFab();
    if (typeof $annoAddDialog.showModal === "function") {
      $annoAddDialog.showModal();
    } else {
      $annoAddDialog.setAttribute("open", "");
    }
    $annoAddComment.focus();
  });

  function showAddError(msg) {
    $annoAddError.textContent = msg;
    $annoAddError.hidden = false;
  }
  function clearAddError() {
    $annoAddError.textContent = "";
    $annoAddError.hidden = true;
  }

  $annoAddCancel.onclick = function () {
    $annoAddDialog.close();
    clearIframeSelection();
    pendingQuote = null;
  };

  $annoAddForm.onsubmit = function (e) {
    e.preventDefault();
    clearAddError();
    var comment = $annoAddComment.value.trim();
    if (!comment) {
      showAddError("批注内容不能为空");
      return;
    }
    if (!pendingQuote || !annoCurrentFile) {
      showAddError("选区已失效,请重新选择文本");
      return;
    }
    fetch("/api/files/" + encodeURIComponent(annoCurrentFile) + "/annotations", {
      method: "POST",
      credentials: credentials(),
      headers: csrfHeaders(),
      body: JSON.stringify({ quote: pendingQuote, comment: comment }),
    }).then(function (r) {
      if (r.status === 201) {
        $annoAddDialog.close();
        clearIframeSelection();
        pendingQuote = null;
        toast("批注已添加");
        refreshAnnoList();
      } else if (r.status === 401) {
        showAddError("session 已过期,请退出批注模式重新进入");
      } else {
        return r.json().then(function (j) {
          showAddError(j.message || ("提交失败 " + r.status));
        });
      }
    }).catch(function () {
      showAddError("网络错误,稍后重试");
    });
  };

  // --- hook into existing preview() (defined earlier in app.js) ---
  //
  // Rather than monkey-patch `preview`, listen for iframe load events. When
  // the preview section becomes visible and the iframe fires load, we capture
  // the current file from the preview name label and refresh annotations.

  // Mark current file from previewName label (which V1's preview() fills with
  // "(" + name + ")"). Cheaper than re-parsing iframe.src.
  $previewFrame.addEventListener("load", function () {
    var m = $previewName.textContent.match(/^\((.+)\)$/);
    if (m) annoCurrentFile = m[1];
    // New document → old selection listeners are gone; re-attach and
    // drop any stale fab from the previous page.
    pendingQuote = null;
    hideAddFab();
    hidePreviewPopover();
    attachSelectionListener();
    applyTocToggle();        // re-apply TOC fold to the freshly loaded DOM
    refreshAnnoList();       // both modes: read-only in read mode, full in anno
    // Restore scroll position if this file was the one we last opened
    // (preview() pre-zeroes LS_LAST_SCROLL on switch, so the only time
    // it's nonzero is when reload re-opens the same file).
    var last = lsStr(LS_LAST_FILE, "");
    var targetY = lsNumber(LS_LAST_SCROLL, 0);
    if (last && m && last === m[1] && targetY > 0) {
      var w = $previewFrame.contentWindow;
      var d = $previewFrame.contentDocument;
      if (w && d) {
        // Clamp to the new doc's scroll range (file might be shorter
        // than when we last read it — e.g. regenerated).
        var max = Math.max(0,
          (d.documentElement.scrollHeight || 0) - (w.innerHeight || 0));
        w.scrollTo(0, Math.min(targetY, max));
      }
    }
    // Throttled save: capture scroll position for restore-on-reload,
    // but only every 500ms so we're not writing to localStorage on
    // every wheel tick.
    var scrollSaveT = null;
    $previewFrame.contentWindow.addEventListener("scroll", function () {
      if (scrollSaveT) return;
      scrollSaveT = setTimeout(function () {
        scrollSaveT = null;
        var d = $previewFrame.contentDocument;
        if (d) lsSetNumber(LS_LAST_SCROLL, d.defaultView.scrollY || 0);
      }, 500);
    });
  });

  // When preview is hidden, clear current file.
  var previewHiddenObserver = new MutationObserver(function () {
    if ($previewSection.hidden) {
      annoCurrentFile = null;
      clearAnnoList();
      pendingQuote = null;
      hideAddFab();
      hidePreviewPopover();
      applyAnnoSidebarVisibility();
    }
  });
  previewHiddenObserver.observe($previewSection, { attributes: true, attributeFilter: ["hidden"] });

  // --- iframe TOC (大纲) fold: parent-driven -------------------------
  // sandbox="allow-same-origin" grants no script execution, so the md→html
  // theme's own JS doesn't run inside the preview. The parent toggles
  // <aside class="sidebar"> directly; .layout is flex, so hiding the sidebar
  // lets <main class="content"> take the full width.
  function applyTocToggle() {
    if (!$tocToggle) return;
    var doc = $previewFrame.contentDocument;
    var sb = doc && doc.querySelector("aside.sidebar");
    if (!sb) {
      // File has no TOC (e.g. generated with --no-toc) — nothing to fold.
      $tocToggle.disabled = true;
      $tocToggle.setAttribute("aria-pressed", "false");
      return;
    }
    $tocToggle.disabled = false;
    $tocToggle.setAttribute("aria-pressed", tocHidden ? "true" : "false");
    sb.style.display = tocHidden ? "none" : "";
  }
  if ($tocToggle) {
    $tocToggle.onclick = function () {
      tocHidden = !tocHidden;
      lsSetBool(LS_TOC_HIDDEN, tocHidden);
      applyTocToggle();
    };
  }

  // First paint: sync the opener tab with any persisted fold.
  applyAnnoSidebarVisibility();

  // After a refresh, auto-resume annotation mode if the session cookie is
  // still valid — no re-entry of the token.
  probeSession(enterAnnoMode, null);
})();
