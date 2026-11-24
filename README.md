# NyayaLens PDF extraction and translation update

This is a merge-ready copy of the NyayaLens app with page-aware PDF text extraction and authenticated clause translation added. It preserves the existing clause analyzer, account authentication, and MongoDB analysis records.

## What changed

- PDF text is extracted one page at a time with PyMuPDF reading-order sorting. Results show short previews for up to 20 pages and identify pages with no selectable text. Sorting improves reading order, but multi-column layouts can still need a human check. The existing 10 MB upload limit remains.
- The results screen can translate original clause headings and text into English, Hindi, Bengali, Tamil, Telugu, Marathi, Spanish, French, or German. Source language can be selected or auto-detected.
- Translations are stored in a new `analysis_translations` collection, keyed to the existing analysis ID, user ID, source language, target language, and source content fingerprint. Existing analysis documents are not rewritten, migrated, or assigned new IDs. Repeating the same translation reuses its saved result.
- Both translation endpoints require the existing bearer-token authentication and verify the user owns the analysis before reading or writing its translation.
- The frontend includes Indic-script font fallbacks. It displays original and translated clause text together and labels the translation informational.
- Demo workspace uploads use `POST /demo/analyze` and are analyzed in memory without writing to MongoDB. Sign-in uploads continue to use the authenticated `POST /upload` route and existing analysis history.
- A translated analysis can be printed to a clean, reflowed PDF with the translated clauses and source text for comparison. This uses the browser's print dialog; choose **Save as PDF**. Export itself is local and makes no translation-provider request. It does not reproduce the original PDF's page design.

## Provider and setup

The provider is **Google Cloud Translation Advanced v3**, using Google's built-in **Neural Machine Translation (`general/nmt`)** model. Google's current [NMT language list](https://docs.cloud.google.com/translate/docs/languages) includes all nine selected languages. The [translateText API](https://docs.cloud.google.com/translate/docs/reference/rest/v3/projects/translateText) accepts up to 30,000 code points per request; this implementation sends smaller batches. PyMuPDF's [`Page.get_text("text", sort=True)`](https://pymupdf.readthedocs.io/en/latest/page.html) orders selectable text by page position.

1. Merge this package's `backend` and `frontend` files into the NyayaLens project. Keep your real `backend/.env` and frontend `.env`; use the included `.env.example` files only to copy variable names. Do not replace or share real credentials.
2. In Google Cloud, select a project, enable the Cloud Translation API, enable billing, and grant the backend identity the least-privilege `roles/cloudtranslate.user` role. Google's [setup guide](https://cloud.google.com/translate/docs/setup) covers project, API, and access setup.
3. Add these values to the existing backend `.env`:

   ```env
   GOOGLE_CLOUD_PROJECT_ID=your-project-id
   GOOGLE_CLOUD_LOCATION=global
   GOOGLE_TRANSLATE_MODEL=general/nmt
   NYAYALENS_TRANSLATION_MAX_CHARS=100000
   ```

   `GOOGLE_CLOUD_PROJECT_ID` is a project identifier, not a credential. The backend uses Application Default Credentials; it does not accept or store a hardcoded API key. For local development, use `gcloud auth application-default login`. In production, use the hosting platform's workload identity or attached service account. See Google's [authentication guide](https://cloud.google.com/translate/docs/authentication).
4. From the backend folder, install the updated dependencies and restart FastAPI:

   ```powershell
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```

5. Start the existing Vite frontend. Its `VITE_API_URL` should point at the same authenticated FastAPI instance as before.

## Publish the project and website

This repository is prepared for a public source repo and a public website. The Git ignore rules exclude local `.env` files, virtual environments, dependencies, and backups; publish only after checking that no real credentials were added to source files.

1. Create a **public** repository on GitHub and add this project. Do not upload `backend/.env`, `frontend/.env`, virtual environments, `node_modules`, or backup files. Keep credentials only in the hosting dashboard.
2. In Render, create a Blueprint from the repository and select the root `render.yaml`. It creates the FastAPI API service. Enter the existing MongoDB Atlas connection string when prompted; Render generates `SESSION_SECRET_KEY` and disables anonymous Demo uploads.
3. Copy the API's public `https://...onrender.com` address from Render. In Vercel, import the same GitHub repository and set the project root to `frontend`. Set these build environment variables before deploying:

   ```text
   VITE_API_URL=https://<your-render-api>.onrender.com
   VITE_ENABLE_DEMO_ANALYSIS=false
   ```

   Vercel's deployment URL is the public website link to share. The free Hobby plan is for personal, non-commercial use.
4. In Render's API service settings, add `FRONTEND_URL` with the exact Vercel site origin (no trailing slash), then redeploy. `OAUTH_BASE_URL` defaults to Render's assigned API URL; keep any explicit override aligned with it. The local CORS origins remain available for development.
5. In MongoDB Atlas, add the Render API service's outbound IP ranges from its **Connect → Outbound** panel to the project's IP access list. Avoid opening the database to every IP. Keep the Atlas database user password only in Render's `MONGODB_URI` secret.
6. New accounts can use the existing email/password flow. GitHub or LinkedIn sign-in requires separate OAuth app credentials and callback URLs; it is optional for hosting the public site. Translation stays unconfigured and makes no provider calls until you set it up.

Render's free API service sleeps after 15 minutes without traffic and may take about a minute to wake. Free hosting is suitable for a personal demo; it is not a production availability guarantee. The public source repository exposes the app code, not the environment secrets. The public website still stores signed-in users' analyzed clauses in your Atlas database, so don't share private legal documents through it without an appropriate privacy policy and access controls.

## API routes

- `POST /demo/analyze` analyzes a PDF or TXT file in local Demo mode without saving to MongoDB. Public hosting disables this endpoint; visitors must sign in before uploading.
- `POST /upload` remains authenticated and continues saving analyses to the signed-in user's MongoDB history.
- `POST /analyses/{analysis_id}/translations` accepts `{"target_language":"hi","source_language":"en"}`. Leave `source_language` out or set it to `null` for automatic detection.
- `GET /analyses/{analysis_id}/translations/{target_language}` returns the latest saved translation for that analysis and target language.

Both routes use the existing `get_current_user` dependency. The new records keep `user_id=str(user['_id'])`; they do not update the `analyses` collection. The `POST` route returns a saved translation when the same source and language pair was already translated.

## Cost and privacy

The per-analysis input cap defaults to 100,000 characters and can be set from 1,000 to 200,000. The API work is split into batches smaller than the documented v3 request maximum. Repeated identical translations use the MongoDB cache. Google currently lists the standard NMT text price as $20 per million input characters after its monthly $10 credit; 100,000 characters is about $2 at that rate before the credit. Review the [current pricing page](https://cloud.google.com/translate/pricing) and set Google Cloud quotas/budgets for your account.

Translation sends the extracted clause text to Google Cloud. Google's [data usage FAQ](https://cloud.google.com/translate/data-usage) says content is used to provide the Translation API and held briefly in memory to return the translation. Decide whether a document may be sent to an external provider before translating it, especially for confidential legal documents.

The existing analyzer still runs on the original source clauses and its predefined risk rules are English-language patterns. Translation does not make risk detection multilingual, and translated text is not analyzed as a substitute for the source. Machine translation can lose legal nuance; compare it with the original and consult a qualified legal professional. The browser-based PDF export prints the translated clauses alongside their source text and does not preserve the original PDF layout.

## Manual verification

1. Sign in and upload a small, selectable-text PDF. Confirm the results show the existing clauses and risk summary plus the PDF page count and per-page text previews.
2. Choose Hindi as the target and auto-detect or English as the source. Confirm each translated clause appears beside the unchanged source clause and that no risk fields change.
3. Select **Print / Save as PDF** and choose **Save as PDF** in the browser print dialog. Confirm the translated clauses and their original text appear in the saved PDF.
4. Navigate to History, reopen the analysis, and request the same target language. The saved translation should load without a second provider translation call. Try the GET route in `/docs` with the same signed-in account.
5. Repeat with Bengali, Tamil, Telugu, Marathi, Spanish, French, German, and English. Confirm Indic text renders in the browser and print preview.
6. Try an analysis ID owned by another account. Both translation routes should respond as not found. Confirm an unauthenticated call returns 401.
7. Try a scanned/image-only PDF. It should report no readable text; a mixed PDF should identify pages without selectable text. OCR is not included.
8. Translate an analysis over the configured character cap. It should return 413 without calling the provider. Keep the existing 10 MB upload check in the flow.

## Not included in this update

OCR for scanned PDFs remains a separate follow-up feature. The translated PDF is a clean, reflowed document with source text for comparison; it does not preserve the original PDF's page layout.
