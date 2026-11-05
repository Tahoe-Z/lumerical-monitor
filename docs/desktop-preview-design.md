# Desktop model and result previews

Approved scope: implement this extension in the desktop app first. Selecting an FDTD/MODE project or task shows a model thumbnail; a dedicated page displays model, field slices, transmission spectra and recorded parameters. The phone can later consume the same data format.

The monitor reads a bounded `<project>.preview.json` sidecar over its existing SSH connection. A separate, explicit generation action opens a hidden Lumerical session on the server, reads saved data and writes only that sidecar. It never runs a solve, saves the engineering project, or switches it to layout mode. This action warns that it checks out a Lumerical license. Running jobs display cached data and cannot trigger preparation from the task panel.

Use actual material contours from `polystencil` for an XY geometry slice, existing E datasets for field intensity, and existing T datasets for spectra. Preserve monitor names, selected wavelength, coordinates and normalization; missing results stay missing. Querying large field datasets is bounded, and large saved projects require pre-export from an existing simulation session. Cache metadata identifies the source by relative path, size and nanosecond mtime; mismatches are visibly stale.

Files: `preview_export.py` (bounded cache and optional Lumerical adapter), `preview_plot.py` (local plots), `preview_ui.py` (Tk preview widgets), small integrations in `app.py`, `client.py`, `remote_probe.py`, packaging/docs, and `test_preview.py`.

Validation: reject root escapes, symlink sidecars, oversized/invalid JSON and nonfinite arrays; verify field axes/wavelength selection and signed transmission; verify no solve/save/layout calls, atomic cache writes and unchanged source; render figures with synthetic data; run all existing tests; open every Tk page offline; inspect screenshots; scan the public tree for original identifiers before publishing.
