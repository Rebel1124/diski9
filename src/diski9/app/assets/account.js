/* Diski 9 account-switching and shared-device safety (Phase 6C.2; T-15).
   Prototype analysis (Weekly Challenge draft and submission, preferences, Your View)
   lives only in this browser tab's sessionStorage and is never sent to the server.
   * Guest signs in or registers with work in the tab: an explicit choice is offered
     to keep it or discard it. Keeping opens a review (Phase 6C.3) that saves the
     compatible work to the account only when the person confirms; nothing is ever
     submitted automatically.
   * A different account signs in in this tab: the previous account's state is
     removed before the page reloads.
   * Sign-out pages clear everything. */
(function () {
  var KEYS = ["ch-session", "ch-prefs", "lab-store", "d9-adopt"];
  var WORK_KEYS = ["ch-session", "lab-store"];
  function clearState() {
    try {
      KEYS.forEach(function (k) { sessionStorage.removeItem(k); sessionStorage.removeItem(k + "-timestamp"); });
    } catch (e) { /* storage unavailable */ }
  }
  function hasWork() {
    try {
      return WORK_KEYS.some(function (k) {
        var raw = sessionStorage.getItem(k);
        if (!raw) { return false; }
        var v = JSON.parse(raw);
        if (v === null || v === undefined) { return false; }
        if (typeof v === "object") { return Object.keys(v).length > 0; }
        return true;
      });
    } catch (e) { return false; }
  }
  function setOwner(v) { try { sessionStorage.setItem("d9-owner", v); } catch (e) {} }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text) { n.textContent = text; }
    return n;
  }
  function offerChoice(current) {
    if (document.getElementById("d9-guest-choice")) { return; }
    var box = el("div", "guest-choice");
    box.id = "d9-guest-choice";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-labelledby", "d9-guest-choice-title");
    var title = el("strong", null, "Keep the analysis you did as a guest?");
    title.id = "d9-guest-choice-title";
    box.appendChild(title);
    box.appendChild(el("p", null,
      "Your draft and Your View adjustments from before you signed in are still in this browser tab. " +
      "Keep them to review what can be saved to your account: nothing is saved until you confirm, " +
      "and nothing is ever submitted automatically."));
    var row = el("div", "guest-choice-actions");
    var keep = el("button", "keep", "Keep");
    keep.type = "button";
    keep.id = "d9-guest-keep";
    var discard = el("button", "discard", "Discard");
    discard.type = "button";
    discard.id = "d9-guest-discard";
    keep.addEventListener("click", function () {
      /* the review (Phase 6C.3) is shown by the page after a reload */
      try {
        sessionStorage.setItem("d9-adopt", JSON.stringify("pending"));
        sessionStorage.setItem("d9-adopt-timestamp", String(Date.now()));
      } catch (e) {}
      setOwner(current);
      window.location.reload();
    });
    discard.addEventListener("click", function () {
      clearState();
      setOwner(current);
      window.location.reload();
    });
    row.appendChild(keep);
    row.appendChild(discard);
    box.appendChild(row);
    document.body.appendChild(box);
  }
  function check() {
    var body = document.body;
    if (!body) { return; }
    if (body.getAttribute("data-clear-state") === "1") {
      clearState();
      try { sessionStorage.removeItem("d9-owner"); } catch (e) {}
      return;
    }
    var marker = document.getElementById("d9-owner");
    if (!marker) { return; }
    var current = marker.getAttribute("data-owner") || "guest";
    var previous = null;
    try { previous = sessionStorage.getItem("d9-owner"); } catch (e) { return; }
    if (previous && previous !== current && previous !== "guest") {
      clearState();
      setOwner(current);
      window.location.reload();
      return;
    }
    if (previous === "guest" && current !== "guest" && hasWork()) {
      /* the owner marker stays "guest" until the person chooses, so a refresh asks again */
      offerChoice(current);
      return;
    }
    setOwner(current);
  }
  var done = false;
  function once() {
    if (done || !document.getElementById("d9-owner")) { return false; }
    done = true;
    check();
    return true;
  }
  function start() {
    if (document.body && document.body.getAttribute("data-clear-state") === "1") { check(); return; }
    if (once()) { return; }
    /* Dash renders the shell after load: check once it exists */
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (once() || tries > 40) { clearInterval(timer); }
    }, 150);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else { start(); }
})();
