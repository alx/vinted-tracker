# Deployment runbook — vinted-tracker

A step-by-step, copy-paste runbook for deploying this tracker to watch
**any** brand / search on **any** Vinted market and alert to a Discord
channel. Written to be followed literally by a human *or* an AI agent.

Complete each step in order. Each step lists the command(s) and the **expected
result** to confirm success before moving on. If a step's check fails, stop and
fix it — do not continue.

---

## 0 — Decide the deployment parameters

Choose values for the parameters below, then use them in every step.

| Parameter | Example | Where it's used |
| --- | --- | --- |
| `DEPLOY_DIR` | `/home/alx/code/vinted-tracker` | Where the repo lives |
| `MARKET` | `fr` | `.env` |
| `SEARCH_QUERY` | `havok` | `.env` (catalog text search) |
| `BRAND_FILTER` | `havok` | `.env` (exact brand match; strongly recommended) |
| `TRACKER_NAME` | `Havok Tracker` | `.env` (Discord name + dashboard title) |
| `DISCORD_WEBHOOK_URL` | `https://discord.com/api/webhooks/…` | `.env` (a channel **webhook**, not a bot token) |
| `POLL_INTERVAL` | `300` | `.env` (seconds) |
| `PAGES` | `2` | `.env` (pages of results to scan) |
| `UI_PORT` | `3110` | dashboard container port |
| `IMAGE` | `vinted-tracker:latest` | docker image tag |

**Choosing `BRAND_FILTER` (important):** run a quick sanity check that the
search isn't polluted by look-alikes before deploying. A bare text search for
a word like `havok` also returns unrelated items (Marvel's *X-Men: Havok*
comics/figures). Set `BRAND_FILTER` to the exact brand (lowercase) so only that
brand is tracked. Leave it empty only if you truly want every search result.

Get a Discord channel **webhook**: Discord → channel → *Edit Channel* →
*Integrations* → *Webhooks* → *New Webhook* → copy URL. You do **not** need a
bot token.

## 1 — Prerequisites (verify each)

```bash
docker --version                 # docker present
docker run --rm hello-world >/dev/null 2>&1 && echo docker-ok   # docker daemon works
```

Expected: `docker-ok`.

## 2 — Get the code

```bash
cd "$DEPLOY_DIR"                 # this repo
ls poller.py ui.py index.html Dockerfile requirements.txt   # expected: all listed
```

If you don't have the repo yet: `git clone <your-repo-url> "$DEPLOY_DIR"`.

## 3 — Create `.env`

```bash
cd "$DEPLOY_DIR"
[ -f .env ] || cp .env.example .env
# edit .env and set: MARKET, SEARCH_QUERY, BRAND_FILTER, TRACKER_NAME,
#                   DISCORD_WEBHOOK_URL, POLL_INTERVAL, PAGES
grep -E '^(SEARCH_QUERY|BRAND_FILTER|DISCORD_WEBHOOK_URL)=' .env   # sanity (mask webhook in real use)
```

Expected: the three keys present and non-empty. **Do not** put the real
webhook in any committed file; `.env` is git-ignored.

## 4 — Prepare the state directory

```bash
mkdir -p "$DEPLOY_DIR/state"
chmod 775 "$DEPLOY_DIR/state"     # so the container's uid 1000 can write it
ls -ld "$DEPLOY_DIR/state"        # expect a writable dir
```

> The container runs as **uid 1000**. Make sure the state dir is owned/writable
> by uid 1000 on the host (e.g. `chown 1000:1000 state` if you aren't uid 1000).

## 5 — Build the image

```bash
docker build -t "$IMAGE" "$DEPLOY_DIR"
docker images "$IMAGE"            # expect a row with vinted-tracker
```

## 6 — Start the poller

```bash
docker rm -f vinted-tracker 2>/dev/null
docker run -d --name vinted-tracker \
  --restart unless-stopped \
  -v "$DEPLOY_DIR/state":/app/state \
  --env-file "$DEPLOY_DIR/.env" \
  "$IMAGE"
docker ps --filter name=vinted-tracker --format '{{.Names}} {{.Status}}'
```

Expected: `vinted-tracker Up …`. Then wait ~10s and check the first cycle:

```bash
sleep 10
docker logs --tail 5 vinted-tracker 2>&1 | tail -5
```

Expected on the **very first** run: a line ending in `PRIMED n items (no
alerts)` (the tracker records what's currently listed silently). Subsequent
cycles log `no changes (active=n)` or `alerts sent: n (active=n)`.

> If you see repeated `VintedRateLimitError`/403 lines, set `PROXY=` in
> `.env` to a residential proxy and restart the container.

## 7 — Start the dashboard

```bash
docker rm -f vinted-tracker-ui 2>/dev/null
docker run -d --name vinted-tracker-ui \
  --restart unless-stopped \
  -p 127.0.0.1:${UI_PORT}:3110 \
  -v "$DEPLOY_DIR/state":/app/state:ro \
  --env-file "$DEPLOY_DIR/.env" \
  "$IMAGE" python ui.py
sleep 2
curl -fsS "127.0.0.1:${UI_PORT}/healthz"      # expected: {"ok": true}
curl -fsS "127.0.0.1:${UI_PORT}/api/items" | head -c 200   # expected: JSON array
```

Open `http://127.0.0.1:${UI_PORT}/` in a browser to see the cards.

## 8 — (Optional) Expose on the tailnet

Only if the host is a Tailscale node and you want remote access. The dashboard
binds to `127.0.0.1`, so tailscale serve can front it:

```bash
tailscale serve --bg --https=${UI_PORT} ${UI_PORT}
tailscale serve status | grep -E "https://|proxy" | grep ${UI_PORT}
```

Expected: a `(tailnet only)` mapping for `:${UI_PORT}`. This is **tailnet-only**
(no public internet, no login) — the tailnet is the access control.

> Do **not** run `tailscale serve reset` on a host that has other live
> mappings.

## 9 — End-to-end verification checklist

Confirm all of the following before declaring the deployment healthy:

- [ ] `docker ps` shows both `vinted-tracker` and `vinted-tracker-ui` **Up** with `restart=unless-stopped`.
- [ ] `docker logs vinted-tracker` shows a successful cycle (PRIMED / no changes), no traceback.
- [ ] `curl 127.0.0.1:${UI_PORT}/api/items` returns a non-empty JSON array.
- [ ] Dashboard page loads cards at `http://127.0.0.1:${UI_PORT}/`.
- [ ] **Alert test:** run `docker exec vinted-tracker python poller.py --test-discord` and confirm a message arrives in the Discord channel. (This posts one "online" message.)
- [ ] Watch `docker logs vinted-tracker` over ~2 poll intervals to confirm it settles to `no changes (active=n)` (no alert storm).

## 10 — Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Permission denied` writing `state/seen.json` in logs | state dir not writable by uid 1000 | `chown 1000:1000 "$DEPLOY_DIR/state"`, restart poller |
| No alerts ever, no errors | webhook empty/wrong | check `DISCORD_WEBHOOK_URL`; run the alert test (step 9) |
| Repeated 403 / `VintedRateLimitError` | datacenter IP blocked | set `PROXY=` to a residential proxy, restart |
| Wrong items tracked | `BRAND_FILTER` empty or misspelled | set `BRAND_FILTER` to the exact brand; restart |
| Dashboard empty but poller has items | two different state dirs | ensure both containers mount the **same** `$DEPLOY_DIR/state` |
| Sold item re-appearing as sold repeatedly | should not happen | each item alerts sold **once** (latch); confirm you're on the latest image |

## 11 — Stop / uninstall

```bash
docker rm -f vinted-tracker vinted-tracker-ui
# tailscale mapping (if you added it):
tailscale serve --https=${UI_PORT} off
# image (optional): docker rmi "$IMAGE"
# state is preserved in "$DEPLOY_DIR/state" if you want to keep history.
```

## 12 — Updating the tracker

```bash
cd "$DEPLOY_DIR" && git pull
docker build -t "$IMAGE" .
docker rm -f vinted-tracker vinted-tracker-ui
# re-run the exact `docker run` commands from steps 6 and 7
```

State survives updates (it's in `state/seen.json`, not the image).
