# Mobile simulation previews and compatible upgrade

**Goal:** Add the already-approved desktop model/field/T/parameter previews to the direct-SSH mobile app. A deliverable described as an in-place update must have the installed APK's signing certificate, unchanged applicationId/storage keys, and a higher versionCode.

**Architecture:** Reuse the desktop's standard-library cache/export helper as an embedded asset. Read previews over the existing SSH probe, generate through a separate SSH channel after confirmation, and draw native Flutter charts. Keep SecureVault, FlutterSecureStorage version/options, storage document key, Android applicationId and backup policies unchanged. Private signing material must remain outside public source and artifacts.

**Tasks**

- [ ] Audit the attached APK certificate/version and locate the matching private key. Block production update delivery if that key is unavailable; a fresh signing key is not a compatible update.
- [ ] Reuse `preview_export.py`/probe dispatch and package their assets. Test source injection, reply framing and interrupted transfer handling before implementing transport.
- [ ] Add controller read/generate operations with current connection and active-job checks; cancel the separate preview channel when leaving the page or pausing.
- [ ] Build four preview tabs using synthetic test fixtures, preserving nonuniform coordinates, signed T, wavelength/cross-section labels and missing-data explanations.
- [ ] Integrate project-file and task-detail entry points. Require explicit confirmation before a licensed server-side generation; no solve/save/layout operations.
- [ ] Run analyzer, existing secure-storage/controller/SSH tests and new preview tests. Verify the old secure-store fixture remains readable without mutation.
- [ ] Build only with persistent, private signing. Verify APK certificate equals the attached installed version before claiming data-preserving installation; do not ask the user to uninstall their existing app.
