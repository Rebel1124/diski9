/* Diski 9 account-switching and shared-device safety (Phase 6C.2).
   Prototype analysis (Weekly Challenge draft and submission, preferences, Your View)
   lives only in this browser tab's sessionStorage. When a different account signs in
   in this tab, the previous account's state is removed; guest state is kept in the
   tab (never adopted into an account). Sign-out pages clear everything. */
(function () {
  var KEYS = ["ch-session", "ch-prefs", "lab-store"];
  function clearState() {
    try {
      KEYS.forEach(function (k) { sessionStorage.removeItem(k); sessionStorage.removeItem(k + "-timestamp"); });
    } catch (e) { /* storage unavailable */ }
  }
  function check() {
    var body = document.body;
    if (!body) { return; }
    if (body.getAttribute("data-clear-state") === "1") {
      clearState();
      try { sessionStorage.removeItem("d9-owner"); } catch (e) {}
      return;
    }
    var el = document.getElementById("d9-owner");
    if (!el) { return; }
    var current = el.getAttribute("data-owner") || "guest";
    var previous = null;
    try { previous = sessionStorage.getItem("d9-owner"); } catch (e) { return; }
    if (previous && previous !== current && previous !== "guest") {
      clearState();
      try { sessionStorage.setItem("d9-owner", current); } catch (e) {}
      window.location.reload();
      return;
    }
    try { sessionStorage.setItem("d9-owner", current); } catch (e) {}
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", check);
  } else { check(); }
  /* Dash renders the shell after load: check again once it exists */
  var tries = 0;
  var timer = setInterval(function () {
    tries += 1;
    if (document.getElementById("d9-owner") || tries > 40) { clearInterval(timer); check(); }
  }, 150);
})();
