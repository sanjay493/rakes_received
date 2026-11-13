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

To let the Chrome extension send data to a local run, start the app with an API token (PowerShell):

```
$env:API_TOKEN = "<your token>"
$env:PYTHONUTF8 = "1"
.\venv\Scripts\python.exe app.py
```

The token can be any text you choose; enter the same one in the extension popup. The extension in this repo sends to `http://127.0.0.1:5000`.

## Use on a second computer (data through Google Drive)

`rake_data.db` isn't kept in git. `db_sync.py` copies it, with the two mapping files, to `My Drive\rakes_received_backup` in Google Drive for Desktop, and restores it from there.

### One-time setup

1. Install Python 3.11, Git and Google Drive for Desktop, signed in to the same Google account as the first computer.
2. Get the code. For a new copy:

   ```
   git clone https://github.com/sanjay493/rakes_received.git
   cd rakes_received
   ```

   If the project is already there, first copy its `rake_data.db` somewhere safe if it holds imports made only on that computer, because the pull deletes that file. Then:

   ```
   git checkout main
   git pull
   ```

3. Install the packages:

   ```
   python -m venv venv
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Bring in the data from Google Drive:

   ```
   .\venv\Scripts\python.exe db_sync.py restore
   ```

5. Start the app with the API token, as shown under Run locally, and open http://127.0.0.1:5000.
6. Load the extension: open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, choose the `chrome_extension` folder, and enter the API token in the popup.

### Daily routine

Import on one computer at a time.

| When | Command |
| --- | --- |
| Before starting work on a computer, with the app stopped | `.\venv\Scripts\python.exe db_sync.py restore` |
| After importing, before moving to the other computer | `.\venv\Scripts\python.exe db_sync.py backup` |
| To see which copy is newer | `.\venv\Scripts\python.exe db_sync.py status` |

After a backup, wait for Google Drive to finish syncing before restoring on the other computer. A backup is safe while the app is running; a restore refuses to run until the app is stopped.

Each backup also keeps a dated copy under `history` (the last 10). A restore first saves the existing database as `rake_data_before_restore.db`. If both computers import without a backup and restore in between, the restore replaces one computer's imports with the other's, and the two copies can't be combined.

`db_sync.py` finds `My Drive` on any drive letter. Set `RAKES_BACKUP_DIR` to use another folder.

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

The extension reads only tables on the open page and never sees FOIS passwords. It runs when its icon is clicked, unless automatic sending is turned on.

To send the Loaded In-Bound list automatically every 5 hours:

1. Open the all-India Loaded In-Bound report on FOIS with **Show All**, click the extension icon and send it once by hand.
2. Tick **Send the Loaded In-Bound list automatically every 5 hours**. Chrome asks once for access to the FOIS site; allow it.
3. Click **Refresh the report and send now** to test it. The popup shows the result, and when the next send is due.

Every 5 hours the extension then reloads the report in that tab, waits for it to finish loading and sends it. It can't log in to FOIS: if the report doesn't come back after the reload (FOIS logged out, or the tab was closed), nothing is sent, the icon shows a red **!** and the popup says why. Chrome, the FOIS tab and the dashboard must be left running, and the computer must stay awake. After Chrome restarts, the extension looks for the report in any open tab of the same site. Untick the box to stop. To change the interval, edit `PERIOD_MINUTES` in `background.js`.

It recognises two reports by their headings:

| Report | Required headings | What happens on send |
| --- | --- | --- |
| Rakes Received | `Sr No`, `Received Time`, `Dispatched Time`, `Transit Time`, `Sttn From`, `Sttn To`, `Cmdt`, `Totl Unts`, `Rake Type` | Rows are added to the dashboard. Rows already there are skipped, so sending twice is safe. |
| Loaded In-Bound | `Crnt Locn`, `Stts Time`, `Sttn From`, `Sttn To`, `Rake Id`, `Expd Arvltime` | The rows become the latest list on the `/inbound` page. Older lists stay in the database but aren't shown. |

Select **Show All** before sending, because the extension only reads rows that are on the page. A Loaded In-Bound report that's filtered or only partly shown becomes the whole latest list, so send the complete report.

The `/inbound` page and its downloads only show rakes going to the plants (`BSCS`, `BSPC`, `DSEY`, `IISD`, `BCME`, `HSPG`, `NHSB`) and pellet conversion agents. Rakes to other destinations stay saved in the database but aren't shown. To change the list, edit `DESTINATION_PLANTS` or `PELLET_AGENTS` in `app.py`, but note that `DESTINATION_PLANTS` also filters the dashboard.

The page also counts rakes by commodity, 50 km distance slab and plant, and shows the km left for each rake. This table, **Rakes in Transit**, leaves out rakes to the pellet conversion agents (`PMRN`, `MOMG`, `GFMK`, `SSPL`, `NKKH`); the page's other lists still show them. Each cell also shows how many rakes are stabled (`STTS CODE` of `ST`), and commodities use the readable names from the commodity mappings, so codes sharing a name are combined. The table is titled **Rakes in Transit**, with the date and time the list was received from FOIS. Within each slab, every source station (`STTN FROM`) with rakes to any plant gets its own row, showing the station name from the station mappings and its code. After a commodity's slabs, **Enroute by Source** rows add up its rakes for each source over all distances, then comes the commodity total. The table's heading row stays in view while scrolling it. The Excel and PDF merge the commodity and distance cells like the page; in the PDF a merged cell can't run over a page break, so a long commodity shows its name once in every block of up to 10 rows. To change the slab width, edit `SLAB_KM` in `app.py`. The page's Download Excel and Download PDF buttons contain the same report and rake list, for the selected destination.

A separate table counts the same rakes by commodity, source, destination and loading date, with one column per day taken from `LDNG TIME`. Commodities run alphabetically and each is merged down its rows; within a commodity, sources run in code order and each is merged down its destinations. Stations show as `NAME (CODE)` using the station mappings, or just the code when there's no name. It reads day-first dates such as `04-11-2026 10:30`, `04/11/26` or `04-NOV-26`. Any other text gets its own column, and a blank time goes under **No date**.

The **All-India** page (`/enroute`) uses the all-India Loaded In-Bound Rake list from FOIS e-Customer (`ecbs/JSP/InBundLRake.jsp`). Send it with the extension like the In-Bound report: it's the same table, so one send updates both pages, and the In-Bound page keeps showing only the plant and agent rakes. A list counts as all-India when any rake in it goes somewhere other than the plants and agents. The page shows the latest all-India list by consigner (`CNSR`) and by consignee (`CNSG`), each with the parties on the other side, and a filter box for codes. Clicking a consigner or consignee code opens `/enroute/rakes` with its rakes from the latest all-India list (summary by the other party, commodity and loading station, then rake by rake, oldest loading first); clicking one of its tags shows just that consigner–consignee pair. A third table covers the last 7 days: for every source station that loaded a rake for consignee `SAIL`, how many rakes it loaded for SAIL and for other consignees. It's built from every list sent in those 7 days, counting a rake once by Rake ID and `LDNG TIME`, so rakes already delivered still count; send the all-India list at least daily for full counts. A fourth table splits the same rakes and sources by loading date (the date in `LDNG TIME`), with SAIL and Others columns for each of the 7 days. Sources loading for SAIL also get their names looked up on FOIS Station Help. Each all-India send keeps about 4,000 rows in `inbound_rakes`.

The km left is the goods distance from `CRNT LOCN` to `STTN TO` on the Railways' [Rates Branch System](https://rbs.indianrail.gov.in/ShortPath/ShortPath.jsp). That site didn't respond to the server when tested from Amsterdam, so the extension does the lookups from the user's browser. After an In-Bound send, it opens a tab that looks up each new station and yard pair, one every 1.5 seconds, and saves the result in the `rail_distances` table. Each pair is only looked up once, and only rakes going to the plants and agents are looked up. If the tab is closed early, the next send picks up the rest.

The same tab first looks up station names on [FOIS Station Help](https://fois.indianrail.gov.in/FOISWebPortal/pages/FWP_SttnHelp.jsp), for each `STTN FROM` and `STTN TO` of those rakes that has no name in the station mappings yet. Found names are added to the station mappings, where they can be edited on the config page; a name already there is never replaced. Every code looked up is recorded in the `station_lookups` table, with an empty name when FOIS doesn't know it, so it's only asked once. FOIS names can be cut short at about 30 characters, and sidings show the firm's name (for example `BSPC` is "M/S. STEEL AUTHORITY OF INDIA"), so edit any that read badly. A lookup that fails, such as when FOIS says its server isn't running, is tried again on the next send.

The **BOBSNM1** page (`/bobsnm1`) lists every `BOBSNM1` rake. Its Loaded In-Bound table takes the rakes from every saved list, each once (by Rake ID, `LDNG TIME` and source) as it was in the last list that had it, and marks those still in the latest list. Its Received Rakes table shows the last 30 days unless dates are chosen; **Show all** lists every one. A first table compares loading in `BOBSN` wagons (`BOBSNM1`, `BOBSNS`) for consignees `SAIL` and `TISC` (TISCO) on each of the last 7 loading dates, with the wagon types and loading stations; it's counted like the All-India page's 7-day tables. To compare other consignees or wagons, edit `COMPARE_CONSIGNEES` and `COMPARE_WAGON_PREFIX` in `app.py`.

If the site moves to another address, update `REPORTS` in `popup.js`, `INBOUND_URL` in `background.js`, the URLs in `lookup.js` and `host_permissions` in `manifest.json`.
