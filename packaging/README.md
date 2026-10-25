# Packaging Docly

Everything here runs on Windows from the project folder with the virtual
environment active.

## 1. Build the app

```bash
pip install -r requirements-build.txt
python tools/build.py
```

This makes `dist/Docly/Docly.exe` and runs it once with `--self-check`.
The build is good only if the report ends with `ALL PASSED`.

If you change `assets/app/docly-app.svg` or `docly-app-small.svg`, run
`python tools/make_icons.py` first.

## 2. Make the MSIX package

Needs the free **Windows SDK**. In its installer, tick only
"Windows App Certification Kit" and "Windows SDK Signing Tools for Desktop Apps".

```bash
python tools/make_msix.py --test-cert
```

* `dist/Docly-<version>.msix` is the one to upload to Partner Center. The Store signs it.
* `dist/Docly-<version>-test.msix` is signed with a test certificate, for installing on your own PC.

The package identity comes from `packaging/msix/identity.json`, copied from
Partner Center > Docly > Product management > Product identity. Change it only
if Partner Center changes.

## 3. Install the test package

1. Double-click `build/cert/docly-test.cer` > Install Certificate > Local Machine >
   "Place all certificates in the following store" > Browse > **Trusted People** > Finish.
   (Once per certificate; needs administrator rights.)
2. Double-click `dist/Docly-<version>-test.msix` > Install.

## 4. Test checklist

Tick each one on the installed package, not on `python main.py`.

- [ ] Start menu shows Docly with the blue icon; the taskbar icon matches
- [ ] Opens to Home; the tour starts on the very first launch only
- [ ] Photo: pick a preset, drop a photo, change the background, Save; the file appears in `Docly_Output` next to the photo
- [ ] Save from a OneDrive folder, a USB drive, and a read-only folder (falls back to Pictures)
- [ ] Signature, PDF (merge, split, shrink), Fill & Sign and Batch each finish one job
- [ ] Settings > Open log folder opens a folder that contains `docly.log`
- [ ] Settings survive closing and reopening (theme, output folder, last preset)
- [ ] Works with Wi-Fi off
- [ ] File Explorer > right-click a PDF > Open with shows nothing new (Docly doesn't take over file types)
- [ ] Settings > Apps > Docly > Uninstall removes it, and the Start menu entry goes away

## 5. Before uploading

Run Microsoft's checker on the Store package (it comes with the SDK):
Start menu > **Windows App Cert Kit** > Validate Store App > choose the `.msix`.
Fix anything marked FAILED; warnings are worth reading but don't block.
