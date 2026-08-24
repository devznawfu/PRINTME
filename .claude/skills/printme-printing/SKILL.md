---
name: printme-printing
description: Use when working on printer integration, win32print, the printer registry, or anything print-job related in PRINTME!.
---

PRINTME! prints via USB, not network printing. Key constraints:

- Real printing (`win32print`) only works on Windows — never test this inside
  the Linux devcontainer. Use the mock backend
  (printme/services/printing/mock_backend.py) for all container-based dev
  and testing.
- 3 physical printers: Brother DCP-L2540DW, DCP-T420W, DCP-T430W, connected
  via USB hub. The admin must select a target printer per job — never
  hardcode a single printer.
- Printer selection and the actual print call belong in
  printme/services/printing/ — keep this isolated from the layout engine and
  job-state logic so the mock/real backend swap stays clean.
- Full real-printer testing only happens on the actual Windows admin PC, not
  during regular dev-container work.
