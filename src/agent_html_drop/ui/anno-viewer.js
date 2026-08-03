/* agent-html-drop — public-page annotation viewer (read-only).
 *
 * Injected server-side into /files/<name>.html ONLY when that file has
 * annotations (see api._inject_viewer). Public visitors get highlights in
 * the text + a click-to-read popover; the full list panel stays folded by
 * default so it never covers the reading column. NO create / edit / delete:
 * writes need the annotation session cookie, which only the management
 * page's token flow can mint. So this script never sends a credential and
 * never calls a write route.
 *
 * The highlight core (buildTextMap / wrapRange / unwrapMarks / …) MIRRORS
 * src/agent_html_drop/ui/app.js on purpose. app.js highlights inside a
 * same-origin sandboxed iframe (the parent DOM-walks it); this script
 * highlights the top-level document it runs in. Same algorithm, two hosts.
 * Kept duplicated rather than shared so the well-tested management page
 * needs no wiring change — if the algorithm drifts, update BOTH.
 */
(function () {
  "use strict";

  // We only ride along on the daemon-served public route. Bail on anything
  // else (e.g. this asset somehow loaded on another page).
  var m = location.pathname.match(/^\/files\/(.+)$/);
  if (!m) return;
  var fileName = decodeURIComponent(m[1]);

  var LS_COLLAPSED = "agent-html-drop:pubAnnoCollapsed";
  function lsBool(key, dflt) {
    try { var v = localStorage.getItem(key); return v === null ? dflt : v === "1"; }
    catch (e) { return dflt; }
  }
  function lsSetBool(key, val) {
    try { localStorage.setItem(key, val ? "1" : "0"); } catch (e) {}
  }
  // Default FOLDED: the panel must not cover the reading column on load.
  // (A returning visitor who explicitly opened it still gets their choice.)
  var collapsed = lsBool(LS_COLLAPSED, true);

  // --- styles (namespaced ahda-*; self-contained, no theme coupling) -----
  var style = document.createElement("style");
  style.textContent = [
    "mark[data-anno-id]{background:rgba(255,196,0,.32);border-radius:2px;padding:0 1px;cursor:pointer;}",
    "mark[data-anno-id].ahda-active{background:rgba(255,196,0,.6);outline:1px solid rgba(255,196,0,.9);}",
    "#ahda-panel{position:fixed;top:16px;right:16px;width:min(320px,calc(100vw - 24px));max-height:70vh;overflow:auto;z-index:99999;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:13px;line-height:1.4;background:rgba(28,30,34,.97);color:#e8e8ea;border:1px solid rgba(255,255,255,.14);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.4);}",
    "#ahda-panel.ahda-collapsed{display:none;}",
    "#ahda-panel header{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;position:sticky;top:0;background:rgba(28,30,34,.97);border-bottom:1px solid rgba(255,255,255,.12);}",
    "#ahda-panel header b{font-weight:600;}",
    "#ahda-panel button{font:inherit;color:#e8e8ea;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);border-radius:6px;padding:2px 8px;cursor:pointer;}",
    "#ahda-panel ul{list-style:none;margin:0;padding:0;}",
    "#ahda-panel li{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.08);cursor:pointer;}",
    "#ahda-panel li:last-child{border-bottom:none;}",
    "#ahda-panel li .q{color:#ffd54f;font-style:italic;word-break:break-word;}",
    "#ahda-panel li .c{margin-top:3px;word-break:break-word;white-space:pre-wrap;}",
    "#ahda-panel li .m{margin-top:4px;color:#9aa0a6;font-size:11px;}",
    "#ahda-panel li.ahda-invalid .q{text-decoration:line-through;}",
    "#ahda-chip{position:fixed;top:16px;right:16px;z-index:99999;font-family:system-ui,sans-serif;font-size:13px;color:#e8e8ea;background:rgba(28,30,34,.97);border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:6px 12px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.35);}",
    "#ahda-chip.ahda-collapsed{display:none;}",
    "#ahda-popover{position:fixed;z-index:100000;max-width:340px;min-width:200px;background:rgba(28,30,34,.98);color:#e8e8ea;border:1px solid rgba(255,255,255,.16);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.45);padding:10px 30px 10px 12px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:13px;line-height:1.4;}",
    "#ahda-popover[hidden]{display:none;}",
    "#ahda-popover .ap-quote{color:#ffd54f;font-style:italic;word-break:break-word;}",
    "#ahda-popover .ap-comment{margin-top:4px;white-space:pre-wrap;word-break:break-word;}",
    "#ahda-popover .ap-meta{margin-top:6px;color:#9aa0a6;font-size:11px;}",
    "#ahda-popover #ahda-popclose{position:absolute;top:4px;right:6px;background:transparent;border:none;color:#9aa0a6;font-size:16px;line-height:1;cursor:pointer;padding:2px 4px;}"
  ].join("\n");
  (document.head || document.documentElement).appendChild(style);

  // --- panel + chip + popover skeleton (static templates only; annotation
  //     data is set via textContent, never innerHTML — stored-XSS defense) -
  var panel = document.createElement("div");
  panel.id = "ahda-panel";
  panel.className = collapsed ? "ahda-collapsed" : "";
  panel.innerHTML =
    '<header><b id="ahda-title">批注</b><button id="ahda-fold" type="button" title="收起">›</button></header><ul id="ahda-list"></ul>';
  var chip = document.createElement("button");
  chip.id = "ahda-chip";
  chip.type = "button";
  chip.className = collapsed ? "" : "ahda-collapsed";
  var popover = document.createElement("div");
  popover.id = "ahda-popover";
  popover.hidden = true;
  popover.innerHTML =
    '<button id="ahda-popclose" type="button" aria-label="关闭">×</button>'
    + '<div class="ap-quote"></div><div class="ap-comment"></div><div class="ap-meta"></div>';
  (document.body || document.documentElement).appendChild(panel);
  (document.body || document.documentElement).appendChild(chip);
  (document.body || document.documentElement).appendChild(popover);

  var $title = document.getElementById("ahda-title");
  var $list = document.getElementById("ahda-list");
  var $fold = document.getElementById("ahda-fold");
  var $popQuote = popover.querySelector(".ap-quote");
  var $popComment = popover.querySelector(".ap-comment");
  var $popMeta = popover.querySelector(".ap-meta");
  var $popClose = document.getElementById("ahda-popclose");
  var popoverCurrent = null;

  function applyFold() {
    panel.classList.toggle("ahda-collapsed", collapsed);
    chip.classList.toggle("ahda-collapsed", !collapsed);
  }
  $fold.onclick = function () { collapsed = true; lsSetBool(LS_COLLAPSED, true); applyFold(); };
  chip.onclick = function () { collapsed = false; lsSetBool(LS_COLLAPSED, false); applyFold(); };
  applyFold();

  function cssEscape(s) { return String(s).replace(/(["\\])/g, "\\$1"); }

  function fmtTs(ts) {
    return new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ");
  }

  // --- highlight core (mirrors ui/app.js; doc == document here) ----------
  var BLOCK_RE = /^(P|DIV|H1|H2|H3|H4|H5|H6|LI|DT|DD|TD|TH|TR|TABLE|SECTION|ARTICLE|HEADER|FOOTER|BLOCKQUOTE|PRE|UL|OL|DL|FIGURE|FIGCAPTION|FORM|FIELDSET|NAV|ASIDE|MAIN|HR)$/;

  function normalize(s) { return String(s).replace(/\s+/g, " ").trim(); }

  function nearestBlock(node) {
    var el = node.parentElement;
    while (el) { if (BLOCK_RE.test(el.tagName)) return el; el = el.parentElement; }
    return null;
  }

  function buildTextMap(doc) {
    var walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
    var nodes = [], starts = [], raw = "", prevBlock = null, node;
    while ((node = walker.nextNode())) {
      var block = nearestBlock(node);
      if (prevBlock !== null && block !== prevBlock) raw += " ";
      prevBlock = block;
      nodes.push(node); starts.push(raw.length); raw += node.nodeValue;
    }
    var norm = "", normToRaw = [], inSpace = false;
    for (var i = 0; i < raw.length; i++) {
      var ch = raw.charAt(i);
      if (/\s/.test(ch)) {
        if (!inSpace) { norm += " "; normToRaw.push(i); inSpace = true; }
      } else { norm += ch; normToRaw.push(i); inSpace = false; }
    }
    return { nodes: nodes, starts: starts, norm: norm, normToRaw: normToRaw };
  }

  function unwrapMarks(doc) {
    var marks = doc.querySelectorAll("mark[data-anno-id]");
    for (var i = 0; i < marks.length; i++) {
      var mk = marks[i], p = mk.parentNode;
      if (!p) continue;
      while (mk.firstChild) p.insertBefore(mk.firstChild, mk);
      p.removeChild(mk);
      p.normalize();
    }
  }

  function wrapRange(doc, map, nStart, nEnd, annoId) {
    var rStart = map.normToRaw[nStart];
    var rEnd = map.normToRaw[nEnd - 1] + 1;
    for (var i = 0; i < map.nodes.length; i++) {
      var node = map.nodes[i], s = map.starts[i], len = node.nodeValue.length;
      if (s + len <= rStart) continue;
      if (s >= rEnd) break;
      var localStart = Math.max(0, rStart - s);
      var localEnd = Math.min(len, rEnd - s);
      if (localEnd <= localStart) continue;
      var middle = node.splitText(localStart);
      middle.splitText(localEnd - localStart);
      var mark = doc.createElement("mark");
      mark.setAttribute("data-anno-id", annoId);
      middle.parentNode.insertBefore(mark, middle);
      mark.appendChild(middle);
    }
  }

  function highlightQuote(doc, entry) {
    var quote = normalize(entry.quote);
    if (!quote) return false;
    var map = buildTextMap(doc);
    var matches = [], from = 0;
    while (matches.length < 500) {
      var idx = map.norm.indexOf(quote, from);
      if (idx < 0) break;
      matches.push(idx); from = idx + quote.length;
    }
    for (var i = matches.length - 1; i >= 0; i--) wrapRange(doc, map, matches[i], matches[i] + quote.length, entry.id);
    return matches.length > 0;
  }

  // --- render + highlight ----------------------------------------------
  var entries = [];

  function entryById(id) {
    for (var i = 0; i < entries.length; i++) if (entries[i].id === id) return entries[i];
    return null;
  }

  function render() {
    $title.textContent = "批注 · " + entries.length;
    chip.textContent = "批注 " + entries.length + " ‹";
    $list.innerHTML = "";
    entries.forEach(function (e) {
      var li = document.createElement("li");
      li.setAttribute("data-anno-id", e.id);
      var q = document.createElement("div"); q.className = "q"; q.textContent = "“" + e.quote + "”"; li.appendChild(q);
      var c = document.createElement("div"); c.className = "c"; c.textContent = e.comment; li.appendChild(c);
      var meta = document.createElement("div"); meta.className = "m";
      meta.textContent = e.author + " · " + fmtTs(e.ts);
      li.appendChild(meta);
      $list.appendChild(li);
    });
  }

  function highlightAll() {
    unwrapMarks(document);
    entries.forEach(function (e) {
      var found = highlightQuote(document, e);
      var li = $list.querySelector('li[data-anno-id="' + cssEscape(e.id) + '"]');
      if (li) li.classList.toggle("ahda-invalid", !found);
    });
    wireMarks();
  }

  // mark click → read its comment in a popover next to the highlight
  function wireMarks() {
    var marks = document.querySelectorAll("mark[data-anno-id]");
    for (var i = 0; i < marks.length; i++) {
      marks[i].onclick = function (ev) {
        ev.stopPropagation();              // keep the doc-click dismiss from firing
        var entry = entryById(ev.currentTarget.getAttribute("data-anno-id"));
        if (entry) showPopover(ev.currentTarget, entry);
      };
    }
  }

  function showPopover(mark, entry) {
    if (popoverCurrent === mark) { hidePopover(); return; }   // toggle
    popoverCurrent = mark;
    $popQuote.textContent = "“" + entry.quote + "”";
    $popComment.textContent = entry.comment;
    $popMeta.textContent = entry.author + " · " + fmtTs(entry.ts);
    popover.hidden = false;
    var r = mark.getBoundingClientRect();
    var pw = popover.offsetWidth, ph = popover.offsetHeight;
    var left = r.left;
    if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
    if (left < 8) left = 8;
    var top = r.bottom + 6;
    if (top + ph > window.innerHeight - 8) top = r.top - ph - 6;   // flip above the mark
    if (top < 8) top = 8;
    popover.style.left = left + "px";
    popover.style.top = top + "px";
  }

  function hidePopover() {
    popover.hidden = true;
    popoverCurrent = null;
  }

  // clicks inside the popover (select text, close) must not dismiss it
  popover.onclick = function (ev) { ev.stopPropagation(); };
  $popClose.onclick = function () { hidePopover(); };
  // any other click / Esc / scroll dismisses the transient popover
  document.addEventListener("click", hidePopover);
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") hidePopover(); });
  window.addEventListener("scroll", hidePopover, true);

  // panel item click → jump to its first mark + briefly emphasize it
  $list.onclick = function (ev) {
    var li = ev.target.closest("li[data-anno-id]");
    if (!li) return;
    var mk = document.querySelector("mark[data-anno-id=\"" + cssEscape(li.getAttribute("data-anno-id")) + "\"]");
    if (mk && mk.scrollIntoView) {
      mk.scrollIntoView({ block: "center", behavior: "smooth" });
      mk.classList.add("ahda-active");
      setTimeout(function () { mk.classList.remove("ahda-active"); }, 1600);
    }
  };

  function init() {
    // Public read; no credential. GET /annotations is unauthenticated.
    fetch("/api/files/" + encodeURIComponent(fileName) + "/annotations", { credentials: "omit" })
      .then(function (r) { return r.ok ? r.json() : { annotations: [] }; })
      .then(function (data) {
        entries = (data && data.annotations) || [];
        if (!entries.length) { panel.remove(); chip.remove(); popover.remove(); return; }
        render();
        highlightAll();
        // Re-highlight once after async renderers (Mermaid / KaTeX) settle,
        // so quotes inside late-rendered markup still light up.
        setTimeout(highlightAll, 2000);
      })
      .catch(function () { panel.remove(); chip.remove(); popover.remove(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
