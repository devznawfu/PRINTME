// Photo Sheets: keeps each sheet's borderless checkbox in sync with
// whether the currently-selected printer actually supports it -
// checked+enabled when it does, unchecked+disabled with a note when
// it doesn't. The server re-validates this independently (see
// admin_photo_sheets.py's print_sheet) - this is just so staff aren't
// staring at a checkbox lying about what'll actually happen.
(function () {
  function syncBorderless(form) {
    const select = form.querySelector('select[name="printer"]');
    const checkbox = form.querySelector('[data-borderless-checkbox]');
    const note = form.querySelector('[data-borderless-note]');
    if (!select || !checkbox) return;

    const selected = select.options[select.selectedIndex];
    const capable = !!selected && selected.dataset.borderless === "true";

    checkbox.disabled = !capable;
    checkbox.checked = capable;
    if (note) note.hidden = capable;
  }

  document.querySelectorAll("[data-sheet-print-form]").forEach((form) => {
    syncBorderless(form);
    const select = form.querySelector('select[name="printer"]');
    if (select) select.addEventListener("change", () => syncBorderless(form));
  });
})();
