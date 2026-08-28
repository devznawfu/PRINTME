// Live quantity stepper for Ready-to-Print job cards: POSTs the new
// quantity to the server and updates every part of the card that
// depends on it (the row's own count, the card's "N prints total"
// summary line, and its price) - not just the row's number, which
// used to leave the total/price looking stale until a full reload and
// read as "did this even save?".
(function () {
  document.querySelectorAll("[data-qty-stepper]").forEach((root) => {
    const jobId = root.dataset.jobId;
    const display = root.querySelector("[data-qty-display]");
    const dec = root.querySelector("[data-qty-dec]");
    const inc = root.querySelector("[data-qty-inc]");
    const card = root.closest("[data-job-card]");
    const fileLineEl = card && card.querySelector("[data-card-file-line]");
    const priceEl = card && card.querySelector("[data-card-price]");

    function adjust(direction) {
      const body = { direction };
      if (root.dataset.rowId) body.row_id = root.dataset.rowId;
      fetch(`/admin/jobs/${jobId}/qty`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.qty !== undefined) display.textContent = String(data.qty);
          if (data.file_line !== undefined && fileLineEl) fileLineEl.textContent = data.file_line;
          if (data.total_cost !== undefined && priceEl) {
            priceEl.textContent = "₱" + data.total_cost.toFixed(2);
          }
        })
        .catch(() => {});
    }

    dec.addEventListener("click", () => adjust("dec"));
    inc.addEventListener("click", () => adjust("inc"));
  });
})();
