# Apps Script Deployment

This folder contains the Apps Script that powers the Wetlab Tracker backend
(sheet sync, email sending, Drive file storage, shared metadata).

The script itself lives on Google's servers, inside the tracker spreadsheet.
This local copy exists so we can track changes in git.

## One-time setup (already done)

- Drive folder `Wetlab_Tracker_Uploads` exists at folder ID
  `1nWYIKZKppCHEhuc9WSG5mwLnHGqLeYjq`, shared with the team + client (Editor).
- `DRIVE_FOLDER_ID` at the top of `Code.gs` is set to that ID.

## Deploying the updated script

When `Code.gs` changes, you must redeploy the Web App for the changes to take
effect on `APPS_SCRIPT_URL`.

1. Open the tracker spreadsheet in Google Sheets.
2. **Extensions → Apps Script** — opens the script editor.
3. Replace the entire contents of the existing `.gs` file with the contents of
   `apps_script/Code.gs` from this repo.
4. Click **Save** (disk icon).
5. Click **Deploy → Manage deployments**.
6. Find the active deployment (the one whose URL matches `APPS_SCRIPT_URL` in
   `index.html`). Click the pencil/edit icon on its row.
7. Under **Version**, choose **New version**, add a short description
   (e.g. "Add cloud storage + meta sync"), then click **Deploy**.
8. The Web App URL stays the same — no frontend change needed.

> **Important:** Do NOT create a brand-new deployment unless you also update
> `APPS_SCRIPT_URL` in `index.html`. Editing the existing deployment keeps the
> URL stable.

## What's new in this version

- `uploadFile`  — POST. Writes a file into `Wetlab_Tracker_Uploads/<batch>/<category>/`. Categories:
  - `ppt` — DNA Status PPT (one per batch)
  - `lib_ppt` — Library Prep PPT (one per batch)
  - `dna` — DNA Status batch files (multiple)
  - `lib` — Library Prep batch files (multiple)
  - `dt` — Data Transfer batch files (multiple)
  - `du` — Data Upload images (multiple)
- `listFiles`   — GET. Returns all files for a batch, grouped by category.
- `listAllFiles`— GET. Returns every batch's files in one call (used on page load).
- `getFile`     — GET. Returns base64 content of a single file by ID (used for downloads).
- `deleteFile`  — POST. Trashes a file by ID.
- `getMeta`     — GET. Returns all key/value pairs from the hidden `_meta` sheet (used to sync mail-sent timestamps, job IDs, directory inputs across users).
- `setMeta`     — POST. Upserts one key/value pair.
- `setMetaBatch`— POST. Upserts many key/value pairs in a single call.

The `_meta` sheet is auto-created on first write. It's a hidden tab in the
tracker spreadsheet with columns `key | value | updated_at`.

## Quick test after deployment

In the script editor, open `Code.gs`, choose the function `listAllFilesAction`
from the function dropdown, and click **Run**. If it returns without errors,
Drive access is wired up correctly. Authorize the script if prompted
(first-time only).
