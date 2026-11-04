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
| `DATA_DIR` | `/data` in the container, the app folder locally | Where the database and mapping files are stored. |
| `PORT` | `8080` in the container, `5000` locally | Port to listen on. Most hosts set this for you. |
| `FLASK_DEBUG` | off | Set to `1` for local auto-reload. Never set it in production. |

### Data on the volume

On first boot, `rake_data.db`, `station_mappings.txt` and `commodity_mappings.txt` are copied from the image to `DATA_DIR`. After that, the volume copies are the live ones: redeploying won't overwrite them, so changes to those files in git won't reach a running deployment. Back up the volume, since it holds all uploaded data.

The image includes `rake_data.db`, so keep it in a private registry if the data is sensitive.
