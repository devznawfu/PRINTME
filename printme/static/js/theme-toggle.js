// Dark/light toggle, persisted per-browser (design-reference/
// admin-dashboard.html). Shared by the staff dashboard and the
// customer upload flow - each side's pre-paint script (admin/partials/
// _theme_script.html or upload/partials/_theme_script.html) already
// applied its own stored preference before first paint; this just
// wires the button to change it afterward. The storage key comes from
// the button's data-storage-key attribute so the two sides don't
// clobber each other's preference, even on the same physical browser;
// omitting it keeps the original staff-only behavior.
(function () {
  const toggle = document.getElementById("theme-toggle");
  if (!toggle) return;

  const storageKey = toggle.dataset.storageKey || "printme-staff-theme";
  const sun = document.getElementById("theme-icon-sun");
  const moon = document.getElementById("theme-icon-moon");

  function isLight() {
    return document.documentElement.getAttribute("data-theme") === "light";
  }

  function render() {
    sun.classList.toggle("hidden", isLight());
    moon.classList.toggle("hidden", !isLight());
    const label = isLight() ? "Switch to dark mode" : "Switch to light mode";
    toggle.setAttribute("aria-label", label);
    toggle.setAttribute("title", label);
  }

  toggle.addEventListener("click", () => {
    const next = isLight() ? "dark" : "light";
    if (next === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    try {
      localStorage.setItem(storageKey, next);
    } catch (e) {}
    render();
  });

  render();
})();
