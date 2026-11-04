# Rakes Received

Flask dashboard for analysing rake transit times, backed by SQLite.

## Run locally

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
set FLASK_DEBUG=1
python app.py
```

Then open http://localhost:5000. Local runs need no password unless you set `APP_PASSWORD`.

## Deploy to the cloud

The `Dockerfile` works on any host that runs containers and offers a persistent volume, such as Fly.io, Railway or a Render disk.

1. Create the service from this repo's `Dockerfile`.
2. Attach a persistent volume mounted at `/data`.
3. Set `APP_PASSWORD`. The container won't start without it.
4. Point the host's health check at `/healthz`, which doesn't need a login.

Run a single instance. SQLite lives on one volume and can't be shared between instances, so hosts without persistent volumes (such as Cloud Run) would lose uploaded data on every restart.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PASSWORD` | none | Turns on the HTTP Basic login. Required in the container. |
| `APP_USERNAME` | `admin` | Login username. |
| `API_TOKEN` | none | Token the Chrome extension uses to import data. Imports are refused until it's set. |
| `DATA_DIR` | `/data` in the container, the app folder locally | Where the database and mapping files are stored. |
| `PORT` | `8080` in the container, `5000` locally | Port to listen on. Most hosts set this for you. |
| `FLASK_DEBUG` | off | Set to `1` for local auto-reload. Never set it in production. |

### Data on the volume

On first boot, `rake_data.db`, `station_mappings.txt` and `commodity_mappings.txt` are copied from the image to `DATA_DIR`. After that, the volume copies are the live ones: redeploying won't overwrite them, so changes to those files in git won't reach a running deployment. Back up the volume, since it holds all uploaded data.

The image includes `rake_data.db`, so keep it in a private registry if the data is sensitive.

## Chrome extension

`chrome_extension/` sends the rake table on the open page to the dashboard, so users don't need to download and upload a CSV.

To install it:

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and choose the `chrome_extension` folder.
3. Pin the extension to the toolbar.

To use it:

1. Log in to FOIS as usual and open the rake report.
2. Click the extension icon. It shows how many rows it found.
3. Enter the API token (it's remembered after the first send) and click **Send to dashboard**.

The extension runs only when its icon is clicked, reads only tables on the open page, and never sees FOIS passwords. Rows already on the dashboard are skipped, so sending the same report twice is safe. A report split across pages needs one send per page.

The table needs these headings: `Sr No`, `Received Time`, `Dispatched Time`, `Transit Time`, `Sttn From`, `Sttn To`, `Cmdt`, `Totl Unts` and `Rake Type`, the same ones CSV upload requires. If the site moves to another address, update `API_URL` in `popup.js` and `host_permissions` in `manifest.json`.
