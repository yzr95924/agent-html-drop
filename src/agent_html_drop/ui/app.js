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

  function fmtTime(unix) {
    var d = new Date(unix * 1000);
    var pad = function (n) { return n < 10 ? "0" + n : n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
      + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  // --- actions ------------------------------------------------------------

  function loadFiles() {
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

        var tdName = document.createElement("td");
        tdName.innerHTML = "<a href=\"#\" data-name=\"" + escapeHtml(f.name) + "\">"
          + escapeHtml(f.name) + "</a>";
        if (f.title) {
          tdName.appendChild(document.createTextNode(" "));
          var sub = document.createElement("span");
          sub.style.color = "var(--fg-dim)";
          sub.textContent = "(" + f.title + ")";
          tdName.appendChild(sub);
        }

        var tdSize = document.createElement("td");
        tdSize.textContent = fmtSize(f.size);

        var tdTime = document.createElement("td");
        tdTime.textContent = fmtTime(f.mtime);

        var tdUrl = document.createElement("td");
        // Inherit body's system UI font (rounded on macOS / Windows / Linux)
        // instead of monospace — the URL is for copy-paste, not code reading.
        tdUrl.style.wordBreak = "break-all";
        tdUrl.style.fontSize = "13px";
        tdUrl.appendChild(document.createTextNode(f.url + " "));
        var copyBtn = document.createElement("button");
        copyBtn.textContent = "复制";
        copyBtn.onclick = function () { copyUrl(f.url); };
        tdUrl.appendChild(copyBtn);

        tr.appendChild(tdName);
        tr.appendChild(tdSize);
        tr.appendChild(tdTime);
        tr.appendChild(tdUrl);
        $tbody.appendChild(tr);
      });
    }).catch(function () {
      // Error toast already shown by api().
    });
  }

  function preview(name) {
    $previewSection.hidden = false;
    $previewName.textContent = "(" + name + ")";
    $previewFrame.src = "/files/" + encodeURIComponent(name);
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

  // Click on filename → preview.
  $tbody.onclick = function (e) {
    var a = e.target.closest("a[data-name]");
    if (a) {
      e.preventDefault();
      preview(a.getAttribute("data-name"));
    }
  };

  // Initial load — list is always public; just call.
  loadFiles();

  /* === annotation mode (extension) ============================== */

  // --- state ---------------------------------------------------------
  var mode = "read"; // "read" | "anno"
  var annoCurrentFile = null;
  var annoEntries = [];

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
    if (mode === "anno") {
      $annoToggle.hidden = true;
      $annoModeHint.hidden = false;
      $annoSidebar.hidden = false;
    } else {
      $annoToggle.hidden = false;
      $annoModeHint.hidden = true;
      $annoSidebar.hidden = true;
      clearAnnoList();
      pendingQuote = null;
      hideAddFab();
    }
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

  $annoToggle.onclick = function () {
    clearAnnoError();
    $annoInput.value = "";
    if (typeof $annoDialog.showModal === "function") {
      $annoDialog.showModal();
    } else {
      $annoDialog.setAttribute("open", "");
    }
    $annoInput.focus();
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
      // Actions: only in anno mode.
      var actions = document.createElement("div");
      actions.className = "actions";
      var delBtn = document.createElement("button");
      delBtn.className = "danger";
      delBtn.textContent = "删除";
      delBtn.onclick = function () { deleteAnno(e.id); };
      actions.appendChild(delBtn);
      li.appendChild(actions);
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

  function highlightIframe() {
    if (!$previewFrame || !$previewFrame.contentDocument) return;
    var doc = $previewFrame.contentDocument;
    if (!doc.body) return;
    unwrapMarks(doc);
    annoEntries.forEach(function (e) {
      var found = highlightQuote(doc, e);
      if (!found) {
        var li = $annoList.querySelector('li[data-anno-id="' + cssEscape(e.id) + '"]');
        if (li) li.classList.add("invalid");
      }
    });
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
    attachSelectionListener();
    if (mode === "anno") refreshAnnoList();
  });

  // When preview is hidden, clear current file.
  var previewHiddenObserver = new MutationObserver(function () {
    if ($previewSection.hidden) {
      annoCurrentFile = null;
      clearAnnoList();
      pendingQuote = null;
      hideAddFab();
    }
  });
  previewHiddenObserver.observe($previewSection, { attributes: true, attributeFilter: ["hidden"] });
})();
