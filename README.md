# FramePort

Private personal desktop tool by Auntonin for preparing and uploading image batches through a user-configured HTTP API. Python + Tkinter, monochrome UI, Windows portable builds.

## Run

Install standard Windows Python 3.12+, then open `start.cmd`. Setup installs the pinned runtime dependencies in `.venv-win`. For a portable build, extract the entire release ZIP and open `FramePort.exe` with `_internal` beside it.

1. Open **ตั้งค่าขั้นสูง → เปลี่ยน API profile** and select your local integration profile.
2. Enter the target website URL. External websites require HTTPS.
3. Use **เข้าสู่ระบบผ่านเว็บไซต์** and log in yourself in the dedicated Edge/Chrome window. The account must be authorized by the target service.
4. Select your spreadsheet and photo folder, check whether the first row is a header, then start. Preview is optional.

The committed `profiles/example.json` is a synthetic template for the local test server, not a real service integration. Keep actual profiles in `.private/` or outside this repository. No target website URL is preconfigured.

## Input

A is ignored. B contains `latitude,longitude`. C is a name. D is a description. Natural filename order assigns five images to each non-empty row. The server creates IDs. Ready static WebP files under the configured limit pass through unchanged. Other images convert at their original pixel dimensions. Conversion, caching, cancellation and uncertain-upload handling remain available.

State lives in `%LOCALAPPDATA%/FramePort`, independently of other applications. `FRAMEPORT_DATA_DIR` overrides this for isolated testing. A new installation starts with a new history: verify the destination before repeating an existing dataset. Do not copy session folders or history databases into Git.

## Development

```powershell
./.venv-win/Scripts/python.exe -m unittest discover -s tests -v
./.venv-win/Scripts/python.exe -m compileall -q app.py importer tests scripts
./.venv-win/Scripts/python.exe -m pip check
./.venv-win/Scripts/python.exe scripts/check-repository.py --staged
```

All ordinary tests use generated fixtures or loopback servers. Set `RUN_BROWSER_LOGIN_TESTS=1` to opt into the browser fixture test. There are no production database tests, migrations, backend source or service credentials in this project.

To build, install `requirements-build.txt`, then run `./build-release.ps1`. It produces an unsigned `FramePort.exe` and a portable ZIP with checksums and third-party licenses under ignored `release/`. Build outputs are local, not Git source files. `FramePort.exe --self-check report.json` uses temporary generated inputs, a loopback API and a test browser. It never needs a real website account.

## Privacy and ownership

This repository is intended to remain private. Source, synthetic tests, a synthetic profile, original UI assets and the licensed WebP encoder are tracked. Real photos, spreadsheets, private profiles, secrets, browser sessions, databases, logs, backups and build artifacts are excluded. A local pre-commit check is installed in this checkout; use `scripts/check-repository.py --staged` in other checkouts before committing. See `SECURITY.md` and `docs/privacy-review.md`.

No open-source license is granted for the application. Third-party components retain their own licenses.
