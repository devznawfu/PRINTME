// Staff dark/light toggle, persisted per-browser (design-reference/
// admin-dashboard.html). The pre-paint script in admin/partials/
// _theme_script.html already applied the stored preference before
// first paint; this just wires the button to change it afterward.
(function () {
  const toggle = document.getElementById("theme-toggle");
  if (!toggle) return;

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
      localStorage.setItem("printme-staff-theme", next);
    } catch (e) {}
    render();
  });

  render();
})();
