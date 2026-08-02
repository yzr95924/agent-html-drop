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
        tdUrl.style.fontFamily = "ui-monospace, monospace";
        tdUrl.style.fontSize = "12px";
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

  function highlightIframe() {
    if (!$previewFrame || !$previewFrame.contentDocument) return;
    var doc = $previewFrame.contentDocument;
    annoEntries.forEach(function (e) {
      var found = false;
      var walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
      var node;
      while ((node = walker.nextNode())) {
        if (normalize(node.nodeValue).indexOf(normalize(e.quote)) !== -1) {
          wrapTextMatch(node, normalize(e.quote), e.id);
          found = true;
        }
      }
      if (!found) {
        var li = $annoList.querySelector('li[data-anno-id="' + cssEscape(e.id) + '"]');
        if (li) li.classList.add("invalid");
      }
    });
  }

  function wrapTextMatch(textNode, normalizedQuote, annoId) {
    // Walk back to find the literal substring in the actual nodeValue (preserving
    // surrounding whitespace). Strategy: find the first index where
    // normalize(nodeValue.substring(i, i + normalizedQuote.length)) == normalizedQuote.
    var s = textNode.nodeValue;
    var i = findNormalizedMatch(s, normalizedQuote);
    if (i < 0) return;
    var matchedText = s.substr(i, normalizedQuote.length + slack(s, i, normalizedQuote.length));
    var before = s.slice(0, i);
    var after = s.slice(i + matchedText.length);
    var mark = textNode.ownerDocument.createElement("mark");
    mark.setAttribute("data-anno-id", annoId);
    mark.appendChild(textNode.ownerDocument.createTextNode(matchedText));
    var parent = textNode.parentNode;
    parent.insertBefore(textNode.ownerDocument.createTextNode(before), textNode);
    parent.insertBefore(mark, textNode);
    parent.insertBefore(textNode.ownerDocument.createTextNode(after), textNode);
    parent.removeChild(textNode);
  }

  function findNormalizedMatch(s, normalizedQuote) {
    // Brute-force linear scan; acceptable for small/medium pages.
    for (var i = 0; i <= s.length - normalizedQuote.length; i++) {
      if (normalize(s.substr(i, normalizedQuote.length)) === normalizedQuote) {
        return i;
      }
    }
    return -1;
  }

  function slack(s, i, baseLen) {
    // How many extra chars can we safely include beyond the normalized length
    // so we don't cut a word? Extend forward while the next char is whitespace.
    var extra = 0;
    while (i + baseLen + extra < s.length && /\s/.test(s.charAt(i + baseLen + extra))) {
      extra++;
    }
    return extra;
  }

  function cssEscape(s) {
    return String(s).replace(/(["\\])/g, "\\$1");
  }

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
    if (mode === "anno") refreshAnnoList();
  });

  // When preview is hidden, clear current file.
  var previewHiddenObserver = new MutationObserver(function () {
    if ($previewSection.hidden) {
      annoCurrentFile = null;
      clearAnnoList();
    }
  });
  previewHiddenObserver.observe($previewSection, { attributes: true, attributeFilter: ["hidden"] });
})();
