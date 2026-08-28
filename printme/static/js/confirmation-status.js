// Turn 2b: replaces "we'll call your name" with a real queue position.
// Polls GET /status/<ticket>.json for every non-failed ticket from this
// submission, on the same 5s interval admin-auto-refresh.js already
// uses elsewhere, and shows the WORST (earliest-stage) status across
// all of them - if any one of several files is still queued, the
// customer is still queued overall.
(function () {
  const el = document.getElementById("queue-status");
  if (!el) return;
  const lineEl = el.querySelector("[data-queue-status-line]");
  const tickets = JSON.parse(el.dataset.tickets || "[]");
  if (tickets.length === 0) return;

  const POLL_INTERVAL_MS = 5000;
  // Ordered worst (least done) to best - the customer-facing state is
  // the WORST of every ticket's own state.
  const RANK = { queued: 0, printing: 1, issue: 2, ready: 3 };

  function describe(worst) {
    const { status, ahead } = worst;
    if (status === "printing") {
      return "Your prints are on the machine right now.";
    }
    if (status === "ready") {
      return "Ready for pickup! Come get your prints.";
    }
    if (status === "issue") {
      return "There's an issue with one of your jobs - please check with staff.";
    }
    if (ahead <= 0) {
      return "You're next in line. We'll call your name when it's ready.";
    }
    return `${ahead} order${ahead === 1 ? "" : "s"} ahead of you. We'll call your name when it's ready.`;
  }

  function poll() {
    Promise.all(
      tickets.map((ticket) =>
        fetch(`/status/${encodeURIComponent(ticket)}.json`, { credentials: "same-origin" })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null)
      )
    ).then((results) => {
      const valid = results.filter(Boolean);
      if (valid.length === 0) return;
      // Worst = lowest rank; ties broken by whichever has more "ahead".
      const worst = valid.reduce((a, b) => {
        const rankA = RANK[a.status] ?? 0;
        const rankB = RANK[b.status] ?? 0;
        if (rankA !== rankB) return rankA < rankB ? a : b;
        return (a.ahead || 0) >= (b.ahead || 0) ? a : b;
      });
      lineEl.textContent = describe(worst);
    });
  }

  poll();
  setInterval(poll, POLL_INTERVAL_MS);
})();
