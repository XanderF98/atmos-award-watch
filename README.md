# Atmos Award Watch

A daily watcher for award flights bookable with Alaska Atmos Rewards points, plus a Model Context Protocol (MCP) server so an AI agent can answer questions about what it has found.

I built it for a real trip: two people, Seattle to northern Italy and back from the south, in October 2027. Award seats open about 11 months ahead and the good ones go quickly, so I wanted something that checks every day and tells me only when a seat is worth acting on.

## How it works

```
GitHub Actions (daily)  --HTTPS-->  seats.aero API (cached award space)
        |
        |-- saves data/latest.json and data/history.csv to this repo
        '-- opens a GitHub issue when a deal is new or its price dropped

Copilot Studio agent  --MCP (Streamable HTTP)-->  server.py  --> the saved data, or a live lookup
```

1. Every morning a scheduled GitHub Actions job runs `watcher.py`.
2. For each watch in `watchlist.json` it makes one API call covering every airport pair and date.
3. `deals.py` applies the rules below and decides what counts as a deal.
4. The job commits a snapshot and one history row per route and cabin, so the repo becomes the price history.
5. If a deal is new, or got cheaper, the job opens an issue. GitHub then notifies me by email and on my phone.

No server or database is needed for the alerts. The MCP server is optional and only adds the ability to ask questions.

## What counts as a deal

All of these are set in `watchlist.json`. Points are per person, one way.

| Rule | Setting | Default |
|---|---|---|
| Points price at or under the limit for the cabin | `max_miles` | first 90,000, business 70,000, premium 50,000, economy 30,000 |
| Enough seats for everyone, when the seat count is known | `passengers` | 2 |
| Taxes and fees under a cap, when known and in US dollars | `max_taxes_usd` | 350 |
| A backup airport only counts if it beats the main airport by a margin | `backup_airports`, `backup_airport_min_savings` | Vancouver and Portland must be 20,000 points cheaper than Seattle |

The limits are starting points. After a week or two of history it is easy to see what normal prices look like and tighten them.

Each watch is a one-way search, because awards price as one-ways and the trip flies into one city and home from another:

```json
{
  "name": "Seattle to Milan",
  "origins": ["SEA", "YVR", "PDX"],
  "destinations": ["MXP", "LIN"],
  "backup_airports": ["YVR", "PDX"],
  "start_date": "2027-10-01",
  "end_date": "2027-10-16"
}
```

## MCP tools

| Tool | What it returns | Cost |
|---|---|---|
| `get_watchlist` | The routes, dates and rules being watched | Free |
| `get_current_deals` | Deals from the latest daily check, cheapest first | Free |
| `get_price_history` | How the cheapest price per route and cabin has moved, and the lowest seen | Free |
| `search_awards` | A live lookup for any route and date range | 1 API call |
| `get_flight_details` | Flight numbers, times, taxes and a booking link for one option | 1 API call |

The tool descriptions tell the agent which tools are free and which spend quota, so it reaches for the saved data first.

## Set it up

You need a [seats.aero](https://seats.aero) Pro subscription for an API key. Pro keys are for personal use and allow 1,000 calls a day; this project uses about 2 to 7.

1. Fork or copy this repo.
2. Create a key at seats.aero and add it as a repository secret named `SEATS_AERO_API_KEY` (Settings, Secrets and variables, Actions).
3. Edit `watchlist.json` for your own routes, dates and limits.
4. In the Actions tab, open "Daily award check" and choose "Run workflow" to test it. After that it runs every day on its own.

To get the alerts, watch the repo with notifications for issues turned on.

## Run it locally

Requires Python 3.10 or newer. The watcher uses only the standard library.

```
python watcher.py --demo          # sample data, no key needed, nothing saved
python watcher.py                 # real run, needs SEATS_AERO_API_KEY
python -m pytest                  # tests run against a local stand-in for the API
```

To run the MCP server:

```
pip install -r requirements.txt
python server.py
```

The MCP endpoint is `http://localhost:8000/mcp`.

## Deploy the MCP server

The server runs as a single web service. On Render:

- Build command: `pip install -r requirements.txt`
- Start command: `python server.py`
- Environment variables:

| Variable | Purpose |
|---|---|
| `SEATS_AERO_API_KEY` | Needed for the two live tools |
| `MCP_API_KEY` | A long random string. When set, every request must send it in an `X-API-Key` header |
| `DATA_BASE_URL` | `https://raw.githubusercontent.com/<you>/atmos-award-watch/main`, so the server reads the results the daily job commits |
| `LIVE_CALL_DAILY_LIMIT` | Optional cap on live lookups per day (default 50) |

## Connect it to a Copilot Studio agent

1. In the agent, add a tool and choose Model Context Protocol.
2. Enter the server's public URL ending in `/mcp`.
3. For authentication choose API key, sent as a header named `X-API-Key`, and paste the value of `MCP_API_KEY`.
4. Create the connection and add it to the agent. The five tools appear with their descriptions.
5. Ask "Any business class deals to Milan?" in the test chat and confirm it reports using a tool.

## Design choices

- **Scheduled job and agent are separate.** The alerts must work even if the agent or its host is down, so the job depends only on GitHub and the data source. The MCP server reads what the job saved.
- **The repo is the database.** Committing a small snapshot each day gives a free, versioned price history with no storage to run.
- **Alert once.** A deal alerts when it first appears or gets cheaper, not every day it still exists. A deal that disappears and comes back alerts again.
- **Rules are plain, tested functions.** `deals.py` has no network or file access, so every rule has a test.
- **Protect the quota.** The API key has a daily limit and belongs to one person. The server caches lookups, caps live calls per day, and can require its own key. The Sleeper server I built before this needed none of that because its data was public and unlimited.
- **Filter twice.** The request asks for one mileage program and the code filters again, so a change in the API cannot let another program's prices trigger an alert.

## Limitations

- **Cached data.** seats.aero's results can be hours old, so a seat can be gone by the time I look. The alert says so, and the airline's site is the final word.
- **One program.** It watches Atmos Rewards only. Other programs are a one-line config change, but the limits would need rethinking.
- **Not yet proven on live data.** I wrote and tested this against a stand-in for the API built from its published spec. The first real runs will show whether any field behaves differently, especially taxes, which I treat as cents.
- **Points only.** Cash fares are not tracked. Google Flights price alerts already do that well.

## A note on how this was built

I built this as a learning project, with Claude as a coding assistant for the code and tests. I chose the scope and rules, and I run it for my own trip.
