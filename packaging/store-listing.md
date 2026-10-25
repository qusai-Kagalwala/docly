# Docly on the Microsoft Store: what to enter in Partner Center

Copy each block into the matching field. Partner Center's limits are noted
next to each one; everything here fits them.

---

## 1. Pricing and availability

| Field | Choose |
|---|---|
| Markets | All markets (the default) |
| Visibility / Audience | Public |
| Discoverability | Make this product available and discoverable in the Microsoft Store |
| Schedule | Release as soon as possible |
| Pricing | **Free** |
| Free trial | No free trial |

## 2. Properties

| Field | Enter |
|---|---|
| Category | **Productivity** |
| Subcategory | (none) |
| Privacy policy URL | Leave empty. Docly collects and sends nothing, so it isn't required. If certification asks for one anyway, we'll publish the short policy below and add the link. |
| Website | https://github.com/qusai-Kagalwala/docly |
| Support contact | An email address you're happy to show publicly |
| System requirements | Minimum: 4 GB memory; 64-bit (x64) |
| Product declarations | Leave all unticked. (Docly has keyboard shortcuts and screen-reader names, but it hasn't had a formal accessibility review, so don't claim that one yet.) |

## 3. Age ratings

Answer the questionnaire honestly; for Docly every content question is **No**:

- Category: a utility / productivity app (not a game, not social, not a browser)
- Violence, fear, sexual content, gambling, drugs, alcohol, tobacco, crude humour, bad language: **No**
- Users can talk to or share content with other users: **No**
- Shares the user's location: **No**
- Digital purchases: **No**
- Unrestricted internet access (a browser or search): **No**
- Collects personal information: **No**

Expected result: suitable for everyone (IARC 3+ / PEGI 3 / ESRB Everyone).

## 4. Packages

Upload **`dist/Docly-1.0.0.0.msix`**, the one *without* `-test`. Partner Center
checks it against your reserved name and publisher; it should show "Validated".

## 5. Store listings — English (United States)

Add **English (India)** too and paste the same text, so the listing reads right
for Indian users.

### Description (up to 10,000 characters)

```
Docly gets your photos, signatures and PDFs ready for online forms in a few clicks, without uploading anything anywhere.

Exam, government, visa and admission portals are strict: a photo must be exactly 200 × 230 pixels and 20–50 KB, a signature must be on a white background, a PDF must be under 300 KB. Docly knows these rules and does the fiddly part for you, fully offline.

PHOTO
Pick your portal (IBPS, UPSC, NEET, JEE, passport, US visa and more), drop a photo and drag the frame to crop. Docly resizes it, hits the KB limit and shows a clear Ready / Needs attention check. Need a white or light-blue background? Docly can replace it, and warns you for authorities that don't accept edited photos.

SIGNATURE
Photograph your signature on paper with your phone. Docly whitens the paper, darkens the ink, trims the edges and sizes it for the portal. It can also make a see-through PNG for signing documents.

PDF
Merge PDFs and photos into one file, drag pages into order, rotate, delete, split, and shrink a PDF to a size limit while keeping text readable.

FILL & SIGN
Type on a form, tick boxes, add the date and place your signature, then save a clean new PDF.

BATCH
Prepare a whole folder of photos, signatures or PDFs at once, with a report of what's ready.

PRIVATE BY DESIGN
Docly works offline. Your files never leave your PC, nothing is uploaded, and there is no account, no ads and no tracking. Your originals are never changed: results are saved as new files in a Docly_Output folder.

Free and open source (MIT licence). Portal rules change: Docly shows each preset's official source so you can double-check before uploading.
```

### Short description (up to 1,000 characters; shown on some Store pages)

```
Resize, crop and compress photos and signatures to any exam, government or visa portal's rules, and merge, split, sign and shrink PDFs. Fully offline: your files never leave your PC.
```

### What's new in this version

```
First release.
```

### Product features (up to 20, 200 characters each)

```
Presets for Indian exam, government and admission portals, plus passport and visa photos
Hits the exact pixel size and KB range, with a clear Ready check
Replace a photo's background with white, off-white or light blue
Clean up a phone photo of your signature, or make it see-through
Merge PDFs and photos, reorder, rotate, split and delete pages
Shrink a PDF to a size limit while keeping text readable
Fill & Sign: type on forms, tick boxes, add the date and your signature
Batch mode for whole folders, with a report
Works offline; nothing is uploaded, no account, no ads
Light and dark mode, keyboard shortcuts, never overwrites your originals
```

### Screenshots (at least 1; 4–6 recommended)

PNG, at least **1366 × 768** (1920 × 1080 is best), landscape. Take them on
Windows so the real Windows font shows:

1. Maximise Docly on a 1920 × 1080 screen (or 1366 × 768 on a laptop).
2. Press **Alt + Print Screen** to copy just the window, paste it into Paint,
   and save it as PNG. (Win + Shift + S also works; choose "Window".)

Shot list (use a photo you're happy to show publicly, never someone else's ID):

| # | Page | What to show | Caption (optional, 200 characters) |
|---|---|---|---|
| 1 | Photo | IBPS preset, a portrait loaded, result card saying Ready to upload | Get the exact size and KB limit your portal asks for |
| 2 | Photo | Background set to Light blue, preview visible | Swap the background in one click |
| 3 | Signature | Before / after of a signature photo | A clean signature from a phone photo |
| 4 | PDF | Page grid with a few pages, Shrink to size card | Merge, reorder and shrink PDFs |
| 5 | Fill & Sign | A form with typed text, a tick and a signature | Fill and sign forms without printing |
| 6 | Home (dark mode) | The home page | Works offline, light and dark |

### Store logos (optional)

Upload `packaging/store/box-art-1080.png` as the **1:1 box art**. If it asks
for a 300 × 300 logo, use `packaging/store/logo-300.png`.

### Search terms (up to 7)

```
passport photo
signature resize
photo resize kb
pdf compress
exam photo
pdf merge
fill and sign pdf
```

### Copyright and trademark info

```
© 2026 Qusai Kagalwala. Docly is open source under the MIT licence.
```

### Developed by

```
Qusai Kagalwala
```

## 6. Submission options

### Restricted capabilities: why Docly needs `runFullTrust`

```
Docly is a classic Win32 desktop app (Python with Qt) packaged as MSIX. runFullTrust is the standard capability for packaged desktop apps; Docly uses it only to open the photos and PDFs the user chooses (file picker or drag and drop) and to save the results as new files next to the originals or in a folder the user picks. It makes no network connections and collects no data.
```

### Notes for certification

```
Docly works fully offline; no account or sign-in is needed.
Quick test: open Photo, choose the preset "IBPS — Photograph", drop any portrait JPEG, and the result card shows "Ready to upload"; click Save to write the result to a Docly_Output folder next to the photo. The PDF, Signature, Fill & Sign and Batch pages work the same way with any PDF or image.
The first launch shows a short guided tour that can be skipped.
```

Leave "Publishing hold options" at publish as soon as it passes.

## 7. Submit

Click **Submit to the Store**. Certification usually takes from a few hours
to about three working days. You'll get an email when it passes or if
anything needs fixing. If it's rejected, the report says which policy and
why; send it to me and we'll fix it and resubmit (a fixed package needs a
higher version, e.g. 1.0.1).

---

## Privacy policy (only if certification asks for one)

```
Docly privacy policy

Docly runs entirely on your computer. It does not collect, store, send or share any personal information. It makes no network connections: no analytics, no crash reporting, no ads, no account.

The photos, signatures and PDFs you open are processed on your PC and saved where you choose. Docly keeps a settings file and a log file in its own app-data folder on your PC; they never leave it, and uninstalling Docly removes them.

Contact: (your support email)
```
