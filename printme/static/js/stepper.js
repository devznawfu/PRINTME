// Generic quantity stepper: wires -/+ buttons around a number display +
// hidden input, driven by data-stepper attributes. Reused by the
// upload form and (later) the admin dashboard's per-job qty control.
//
// <div data-stepper data-min="1" data-max="99" data-value="1">
//   <button data-stepper-dec>-</button>
//   <span data-stepper-display></span>
//   <input type="hidden" data-stepper-input name="qty">
//   <button data-stepper-inc>+</button>
// </div>
(function () {
  function initStepper(root) {
    const min = parseInt(root.dataset.min || "1", 10);
    const max = parseInt(root.dataset.max || "99", 10);
    let value = parseInt(root.dataset.value || String(min), 10);

    const display = root.querySelector("[data-stepper-display]");
    const input = root.querySelector("[data-stepper-input]");
    const dec = root.querySelector("[data-stepper-dec]");
    const inc = root.querySelector("[data-stepper-inc]");

    function render() {
      display.textContent = String(value);
      input.value = String(value);
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    dec.addEventListener("click", () => {
      value = Math.max(min, value - 1);
      render();
    });
    inc.addEventListener("click", () => {
      value = Math.min(max, value + 1);
      render();
    });

    render();
  }

  document.querySelectorAll("[data-stepper]").forEach(initStepper);
})();
