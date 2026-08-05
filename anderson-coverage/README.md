# Anderson Coverage Checker

A web tool to check **panel/capture coverage** and **sample read-depth coverage**
for NGS target (BED) panels — by gene, multiple genes, chromosome region,
transcript (NM/NR/XM/XR/ENST/ENSG), or rs ID — with one-click PDF reports.

Two layers of coverage in every report:

1. **Panel coverage** — is the gene / region / variant in the capture design, and
   how much of it (from the BED target intervals).
2. **Sample read-depth coverage** *(always included)* — real sequencing depth over
   those targets, read from the precomputed coverage DB: mean / min depth and
   **% of target bases ≥ 1× / 10× / 20× / 30× / 50× / 100×**, plus a **Combined**
   (average across all reference samples) row.

## Query types (auto-detected)

| Type         | Example                          |
|--------------|----------------------------------|
| Gene         | `BRCA1`                          |
| Multiple genes | `BRCA1, BRCA2, TP53`           |
| Chr region   | `chr17:43044295-43125483`        |
| Transcript   | `NM_007294.4`                    |
| rs ID        | `rs6265` (resolved via Ensembl REST) |

PDF filename follows the query: `BRCA1 coverage.pdf`, `listed gene coverage.pdf`,
`rs6265 coverage.pdf`, etc. (Print / Save PDF button).

## Setup

```bash
git clone https://github.com/andersoninhousepipeline-dot/anderson-coverage.git
cd anderson-coverage
pip install -r requirements.txt
./start.sh                          # http://<host>:8100   (PORT=8101 ./start.sh to change)
```

That's it — the committed **`coverage.db`** holds the precomputed reference
coverage, so the tool runs straight from the repo **with no BAM files**.

Requires Python 3 with Flask and requests. rs-ID lookups call
`rest.ensembl.org` (needs internet).

### Sample coverage source

Sample read-depth coverage comes entirely from the precomputed **coverage DBs**
(`coverage.db`, plus any other `*.db` alongside it — one panel per DB). Values
are exact for mean and every `% ≥ Nx`. A panel with no matching DB reports panel
coverage only.

The DBs are built offline from BAMs with mosdepth — see [build/](build/)
(`run_mosdepth.sh` then `build_db.py`). That build step is the only thing that
ever touches BAM files; the running app never reads them.

## Server control

```bash
./start.sh    ./status.sh    ./restart.sh    ./stop.sh
```

`status.sh` reports RUNNING/STOPPED, uptime, memory, HTTP health and panel count.

## Panels (BED files)

The reference (Twist Spikein) panel comes from `coverage.db`. In addition, every
`*.bed` under `BED_DIR` is auto-discovered and selectable (panel coverage only,
unless a matching `*.db` is present).
Mixed vendor annotation styles are supported (Twist `Gene;NM_…`, Roche
`gene_symbol=…`, Sophia `Gene:NM:exon`, comma / tab / plain). Region and rs-ID queries work on any BED; gene /
transcript search needs an annotated 4th column.

## Reference samples

The reference sample types (Normal Male, Normal Female, Male/Female Infertility,
AF, POC) and their replicate counts are stored in the coverage DB, built offline
from the reference BAMs. No BAMs or sample identifiers are committed to the repo.

Every report also includes a **Case vs reference** panel: each case type
(Male/Female Infertility, AF, POC) is flagged when its mean depth falls below the
sex-matched Normal reference range (20% under the reference mean, with a 20×
absolute floor).
Male Infertility → Normal Male, Female Infertility → Normal Female, AF/POC →
pooled Normal. Regions not covered in the reference (e.g. chrY in females) show
**n/a** instead of a false flag.

> **Note:** the reference BAMs are **not** in this repository (too large, and
> private) — and are not needed to run the tool, since `coverage.db` carries the
> precomputed depth. The published GitHub Pages site is an informational landing
> page only.

Replicates of a type are aggregated into one row when the DB is built: **mean of
replicate means**, worst-case min, and mean %≥threshold. Replicate count shows as
`n=…`.

**To add or update samples:** rebuild the DB against the new reference BAMs
(`build/run_mosdepth.sh` + `build/build_db.py`), commit the refreshed
`coverage.db`, then `./restart.sh`.

Sample read-depth is **mandatory** (always shown for all types) so every report
shows both BED coverage and real sample coverage.

## API

- `GET /api/query?q=<term>&panel=<name>` → JSON report (BED + sample depth)
- `GET /api/bed?q=<term>&panel=<name>`   → matched intervals as BED
- `GET /api/panels` · `GET /api/samples`

## Security / deployment notes

This is an internal, read-only lab tool (no upload/write endpoints). For a trusted
LAN it runs as-is. For shared or untrusted networks use
`HOST=127.0.0.1 ./start.sh` (default bind is `0.0.0.0` for LAN access) behind an
authenticating reverse proxy.

rs-ID input is validated (`rs\d+`) and URL-encoded before the Ensembl call; the
rs-ID cache is size-bounded; API errors are logged server-side and return a
generic message. The dev server is fine for internal use; for heavier load run
behind gunicorn/uwsgi.

## Files

- `app.py` — Flask server + single-page UI (Anderson-branded)
- `coverage_index.py` — in-memory BED index (bisect overlap + token map)
- `coverage_db.py` — reads the precomputed coverage DBs (sample depth source)
- `static/anderson.png` — brand logo (header + PDF)
- `start.sh` / `stop.sh` / `status.sh` / `restart.sh` / `server.conf`
