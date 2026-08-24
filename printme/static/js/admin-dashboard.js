// Live quantity stepper for Ready-to-Print job cards: PATCHes the new
// quantity to the server (so pricing stays correct) instead of a full
// page reload for every click.
(function () {
  document.querySelectorAll("[data-qty-stepper]").forEach((root) => {
    const jobId = root.dataset.jobId;
    const display = root.querySelector("[data-qty-display]");
    const dec = root.querySelector("[data-qty-dec]");
    const inc = root.querySelector("[data-qty-inc]");

    function adjust(direction) {
      fetch(`/admin/jobs/${jobId}/qty`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ direction }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.qty !== undefined) display.textContent = String(data.qty);
        })
        .catch(() => {});
    }

    dec.addEventListener("click", () => adjust("dec"));
    inc.addEventListener("click", () => adjust("inc"));
  });
})();
