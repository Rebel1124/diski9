/* Diski 9 client-side helpers (no framework). */
window.dccFunctions = window.dccFunctions || {};

/* Probability threshold: the exact value above the slider thumb. */
window.dccFunctions.thresholdLabel = function (value) {
  return value <= 0 ? "Any" : Math.round(value) + "%";
};

/* Estimated-goal boxes are text inputs (so they can show 1.60, not 1.6). Arrow keys
   still step them like number inputs: 0.01 for final estimates, 0.05 for category
   adjustments. Values are validated on the server. */
document.addEventListener("keydown", function (e) {
  const el = e.target;
  if (!(el instanceof HTMLInputElement)) return;
  const box = el.closest(".goal-input");  // Dash 4 puts the className on a wrapper
  if (!box || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
  const step = box.classList.contains("step-005") ? 0.05 : 0.01;
  const current = parseFloat((el.value || "0").replace(",", ".")) || 0;
  let next = Math.round((current + (e.key === "ArrowUp" ? step : -step)) * 100) / 100;
  const min = box.classList.contains("allow-negative") ? -10 : 0;
  next = Math.min(10, Math.max(min, next));
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(el, next.toFixed(2));
  el.dispatchEvent(new Event("input", { bubbles: true }));
  e.preventDefault();
});
