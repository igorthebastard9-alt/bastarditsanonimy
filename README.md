# ADKAnon API

ADKAnon is a dedicated wrapper around the official [Fawkes](https://sandlab.cs.uchicago.edu/fawkes) cloaking library. It accepts a batch of four face images, runs them through Fawkes to generate cloaked variants that poison facial-recognition models, and returns the processed files as a ZIP archive. The service is designed to run on Railway and integrates cleanly with Lovable creator tools.

## Features

- Flask API with `/api/anon` endpoint protected by `x-api-key`
- Batch processing of exactly four images per request
- True Fawkes cloaking (low mode by default, ArcFace extractor_2) executed via the upstream library
- Zip archive response containing the `*_cloaked` images produced by Fawkes
- Structured logging emitted directly from the processing pipeline for observability

## Quick start

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set the API key**
   ```bash
   export ADKANON_API_KEY=your-secret
   ```

3. **Run the service locally**
   ```bash
   flask --app app run
   ```

4. **Call the endpoint**
   ```bash
   curl -X POST \
        -H "x-api-key: your-secret" \
        -F "files=@image1.jpg" \
        -F "files=@image2.jpg" \
        -F "files=@image3.jpg" \
        -F "files=@image4.jpg" \
        http://127.0.0.1:5000/api/anon --output anon.zip
   ```

## Deployment on Railway

- Commit the repository.
- Create a new Railway project pointing at the repo.
- Set the environment variable `ADKANON_API_KEY`.
- *(Optional)* Tune Fawkes via environment variables:
  - `ADKANON_MODE` (`low`, `mid`, `high`) – defaults to `low`
  - `ADKANON_BATCH_SIZE` – defaults to `1`
  - `ADKANON_OUTPUT_FORMAT` (`png` or `jpeg`) – defaults to `png`
  - `ADKANON_EXTRACTOR` (`extractor_2` or `extractor_0`) – defaults to `extractor_2`
- Deploy; Railway will install Python dependencies and start Gunicorn via the `Procfile`.
- On the first run Fawkes will download its ArcFace model weights (~100 MB) to the container; leave the service running until the download completes.

## Lovable integration hints

- Base URL: your Railway domain (e.g. `https://adkanon.up.railway.app`).
- Endpoint: `POST /api/anon` with `multipart/form-data` field `files` provided exactly four times.
- Authentication: `x-api-key: ${ADKANON_API_KEY}` stored as a Lovable secret.
- Response: ZIP binary; configure Lovable to surface or download the returned archive.

## Logging

The Fawkes runner logs each major step (`[LOG …]` lines) and the API wrapper forwards stdout/stderr to Railway. Use `railway logs` to observe the cloaking pipeline and diagnose missing-face scenarios.
