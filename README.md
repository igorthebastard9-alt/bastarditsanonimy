# ADKAnon API

ADKAnon is a lightweight anonymization microservice inspired by the Fawkes API wrapper. It accepts a batch of four images, applies destructive anonymization transforms, and returns the processed files as a ZIP archive. The service is designed to run on Railway and integrates cleanly with Lovable creator tools.

## Features

- Flask API with `/api/anon` endpoint protected by `x-api-key`
- Batch processing of exactly four images per request
- Image metadata removal, pixelation, noise, and randomized overlays for anonymization
- Zip archive response
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
- Deploy; Railway will install Python dependencies and start Gunicorn via the `Procfile`.

## Lovable integration hints

- Base URL: your Railway domain (e.g. `https://adkanon.up.railway.app`).
- Endpoint: `POST /api/anon` with `multipart/form-data` field `files` provided exactly four times.
- Authentication: `x-api-key: ${ADKANON_API_KEY}` stored as a Lovable secret.
- Response: ZIP binary; configure Lovable to surface or download the returned archive.

## Logging

The anonymization script logs each major step. These logs are printed to STDOUT by the API wrapper, making them visible inside Railway's live logs for observability.
