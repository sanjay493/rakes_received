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

1. On the `/inbound` page, click **Download Extension** and unzip the file into a folder you'll keep. (On a computer with this repo, you can use the `chrome_extension` folder instead.)
2. Open `chrome://extensions` and turn on **Developer mode**.
3. Click **Load unpacked** and choose the folder.
4. Pin the extension to the toolbar.

Chrome doesn't let a website install an extension directly, so these steps are needed once on each computer. To update, unzip a new download over the same folder and click the extension's reload icon on `chrome://extensions`. The download needs the site login and doesn't include the API token, so give the token to each user separately.

To use it:

1. Log in to FOIS as usual and open the rake report.
2. Click the extension icon. It shows how many rows it found.
3. Enter the API token (it's remembered after the first send) and click **Send to dashboard**.

The extension runs only when its icon is clicked, reads only tables on the open page, and never sees FOIS passwords.

It recognises two reports by their headings:

| Report | Required headings | What happens on send |
| --- | --- | --- |
| Rakes Received | `Sr No`, `Received Time`, `Dispatched Time`, `Transit Time`, `Sttn From`, `Sttn To`, `Cmdt`, `Totl Unts`, `Rake Type` | Rows are added to the dashboard. Rows already there are skipped, so sending twice is safe. |
| Loaded In-Bound | `Crnt Locn`, `Stts Time`, `Sttn From`, `Sttn To`, `Rake Id`, `Expd Arvltime` | The rows become the latest list on the `/inbound` page. Older lists stay in the database but aren't shown. |

Select **Show All** before sending, because the extension only reads rows that are on the page. A Loaded In-Bound report that's filtered or only partly shown becomes the whole latest list, so send the complete report.

The `/inbound` page and its downloads only show rakes going to the plants (`BSCS`, `BSPC`, `DSEY`, `IISD`, `BCME`, `HSPG`, `NHSB`) and pellet conversion agents. Rakes to other destinations stay saved in the database but aren't shown. To change the list, edit `DESTINATION_PLANTS` or `PELLET_AGENTS` in `app.py`, but note that `DESTINATION_PLANTS` also filters the dashboard.

The page also counts rakes by commodity, 50 km distance slab, and plant or pellet conversion agent (`PMRN`, `MOMG`, `GFMK`, `SSPL`, `NKKH`), and shows the km left for each rake. Each cell also shows how many rakes are stabled (`STTS CODE` of `ST`), and commodities use the readable names from the commodity mappings, so codes sharing a name are combined. The table is titled **Rakes in Transit**, with the date and time the list was received from FOIS. Within each slab, every source station (`STTN FROM`) with rakes to any plant or agent gets its own row, showing the station name from the station mappings and its code. After a commodity's slabs, **Enroute by Source** rows add up its rakes for each source over all distances, then comes the commodity total. The table's heading row stays in view while scrolling it. The Excel and PDF merge the commodity and distance cells like the page; in the PDF a merged cell can't run over a page break, so a long commodity shows its name once in every block of up to 10 rows. To change the slab width, edit `SLAB_KM` in `app.py`. The page's Download Excel and Download PDF buttons contain the same report and rake list, for the selected destination.

A separate table counts the same rakes by commodity, source, destination and loading date, with one column per day taken from `LDNG TIME`. Commodities run alphabetically and each is merged down its rows; within a commodity, sources run in code order and each is merged down its destinations. Stations show as `NAME (CODE)` using the station mappings, or just the code when there's no name. It reads day-first dates such as `04-11-2026 10:30`, `04/11/26` or `04-NOV-26`. Any other text gets its own column, and a blank time goes under **No date**.

The **All-India** page (`/enroute`) uses the all-India Loaded In-Bound Rake list from FOIS e-Customer (`ecbs/JSP/InBundLRake.jsp`). Send it with the extension like the In-Bound report: it's the same table, so one send updates both pages, and the In-Bound page keeps showing only the plant and agent rakes. A list counts as all-India when any rake in it goes somewhere other than the plants and agents. The page shows the latest all-India list by consigner (`CNSR`) and by consignee (`CNSG`), each with the parties on the other side, and a filter box for codes. A third table covers the last 7 days: for every source station that loaded a rake for consignee `SAIL`, how many rakes it loaded for SAIL and for other consignees. It's built from every list sent in those 7 days, counting a rake once by Rake ID and `LDNG TIME`, so rakes already delivered still count; send the all-India list at least daily for full counts. Sources loading for SAIL also get their names looked up on FOIS Station Help. Each all-India send keeps about 4,000 rows in `inbound_rakes`. After every send, lists older than about 6 months (183 days, `INBOUND_KEEP_DAYS` in `app.py`) are deleted, except the latest list and the latest all-India list, which the pages show however old they are.

The km left is the goods distance from `CRNT LOCN` to `STTN TO` on the Railways' [Rates Branch System](https://rbs.indianrail.gov.in/ShortPath/ShortPath.jsp). That site didn't respond to the server when tested from Amsterdam, so the extension does the lookups from the user's browser. After an In-Bound send, it opens a tab that looks up each new station and yard pair, one every 1.5 seconds, and saves the result in the `rail_distances` table. Each pair is only looked up once, and only rakes going to the plants and agents are looked up. If the tab is closed early, the next send picks up the rest.

The same tab first looks up station names on [FOIS Station Help](https://fois.indianrail.gov.in/FOISWebPortal/pages/FWP_SttnHelp.jsp), for each `STTN FROM` and `STTN TO` of those rakes that has no name in the station mappings yet. Found names are added to the station mappings, where they can be edited on the config page; a name already there is never replaced. Every code looked up is recorded in the `station_lookups` table, with an empty name when FOIS doesn't know it, so it's only asked once. FOIS names can be cut short at about 30 characters, and sidings show the firm's name (for example `BSPC` is "M/S. STEEL AUTHORITY OF INDIA"), so edit any that read badly. A lookup that fails, such as when FOIS says its server isn't running, is tried again on the next send.

If the site moves to another address, update `REPORTS` in `popup.js`, the URLs in `lookup.js` and `host_permissions` in `manifest.json`.
