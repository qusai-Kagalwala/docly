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

The test certificate is self-signed, so Windows must trust it as a root
(Trusted People alone gives error 0x800B0109). Open **PowerShell as
administrator** in the project folder:

```powershell
Import-Certificate -FilePath build\cert\docly-test.cer -CertStoreLocation Cert:\LocalMachine\Root
Import-Certificate -FilePath build\cert\docly-test.cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople
```

Click **Yes** if Windows warns about installing a root certificate. Then
double-click `dist/Docly-<version>-test.msix` > **Install**.

When you've finished testing, remove the certificate again (same admin
PowerShell). The installed app keeps working; only new test installs need it.

```powershell
Get-ChildItem Cert:\LocalMachine\Root, Cert:\LocalMachine\TrustedPeople, Cert:\CurrentUser\My |
  Where-Object Subject -eq "CN=775C1D17-053C-4160-976D-B6782AF2C690" | Remove-Item
```

The Store package is signed by Microsoft, so people installing from the
Store never need any of this.

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
