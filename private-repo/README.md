# Setting up the private results repo

The daily job runs in a private repo so the results stay private (see "How it works" in the main README). It takes about five minutes.

1. Create a new **private** GitHub repo, for example `atmos-award-data`.
2. Copy `watch.yml` from this folder to `.github/workflows/watch.yml` in that repo.
3. In the private repo, add a secret named `SEATS_AERO_API_KEY` (Settings, Secrets and variables, Actions).
4. Optional: add your own `watchlist.json` to the private repo. Without one, the job uses the example in the public repo.
5. In the Actions tab, open "Daily award check" and choose "Run workflow".

After a run, the private repo's front page is the dashboard: the trip table, the chart, which dates are open and which routes are covered. New deals arrive as issues in that repo.

## Pausing to save money

The subscription is only needed while the job runs. To pause, cancel it and delete the secret: the job then skips quietly and the history stays. Add the secret back to resume.
