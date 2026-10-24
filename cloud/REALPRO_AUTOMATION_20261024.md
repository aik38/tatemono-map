# RealPro weekly acquisition

## Boundaries

- `tatemono_map.cloud.realpro`: verified RNP login (approved terms fingerprint only), fresh Fukuoka company catalog, company ID checks, municipality/town selection and PDF acquisition.
- `tatemono_map.cloud.realpro_weekly`: private company receipts, retry/resume, Ulucks completion gate, and connection to the production `realpro_batch` parser/import/QC/release functions.
- `tatemono_map.cloud.realpro_login_check`: login-only diagnostics; does not collect PDFs or open the official SQLite.
- Latest owner instruction: use the existing Secret Manager credential; no password change or password rotation gate.

No Parser, matching algorithm, DB schema, Ulucks collector, Mansion Review, Pages workflow or Web UI changes are part of this adapter. The only existing importer interface extension is an optional `public_preservation_proof` flag: a successful Fukuoka update outside the site's publication geography uses the existing `batch.public_proof` preservation check. Its default is unchanged. Private municipalities remain in the official master and remain excluded from the public database.

## Production entry point

```
python -m tatemono_map.cloud.realpro_weekly --weekly --commit --verify-web
```

The RealPro Scheduler launches the job at Monday 04:05 JST. This is a wake-up time, not permission to collect concurrently: the process reads Cloud Run execution status, requires an Ulucks execution from that Monday 04:00 JST or later, and waits until every Ulucks execution has completed. Both successful and failed terminal outcomes allow progress. Missing executions and unavailable status never authorize collection. The Ulucks runtime image, arguments, environment, task configuration and 04:00 Scheduler are unchanged.

A RealPro-only seven-hour acquisition lease prevents concurrent collectors without taking Ulucks' shared collection lease. The runtime task timeout is six hours. Integration separately takes the existing shared collection lease, reads the latest HEAD, verifies/backups master and public, and uses the existing HEAD generation CAS. A concurrent winner is never overwritten. Immutable cycle/company receipts prevent repeated downloads on task retry. Failed companies retain their prior SQLite snapshot; no failed request is classified as zero rooms or ended availability.

Before starting acquisition the weekly entry also waits for any live canonical-store lease to finish, without deleting or stealing it. The normal Job has one task retry; successful PDF receipts and completed cycle integration are reused by that retry.

## Representative proof and resume

```
python -m tatemono_map.cloud.realpro_weekly --companies 15974,22452 --cycle proof-20261024 --commit
```

This explicit mode accepts only two or three company IDs. It has no weekly completion gate and never implies an all-company acquisition. Reuse the same cycle when resuming it; do not invent a new cycle to redownload successful inputs.

Private evidence:

- `private-inputs/realpro/cycles/<cycle>/companies/<id>/download.json`: verified-format raw PDF reference, selection, hash and acquisition time, saved before PDF accounting.
- `.../acquisition.json`: PDF page/room verification completed.
- `private-inputs/realpro/originals/<sha256>/realpro-<id>.pdf`: original bytes.
- `private-runs/<run>/realpro-company-catalog.json`: all observed company IDs, including empty/unavailable links.
- `private-runs/<run>/companies/<id>/parsed.json` and `result.json`: parse evidence and outcome; source exceptions are never logged verbatim.
- `private-runs/<run>/realpro-acquisition-manifest.json`, `realpro-report.json`, `realpro-final-result.json`.
- `private-inputs/realpro/cycles/<cycle>/integration.json`: completed integration receipt. Duplicate-only input does not create a release. Production Web is checked against the exact release ID and public SHA using the existing Pages path.

## Recovery and permissions

The initial immutable backup prefix is `deployment-backups/realpro/automation-20261024T1350Z/`; it contains the current master/public, HEAD, RealPro/Ulucks Job settings, Ulucks Scheduler, and affected IAM settings. Initial official release: `20261024T102347Z-29a56d3513af`, HEAD generation `1792837477938294`. Always reread HEAD before any later update; these are history, not restoration targets.

Reuse the existing `tatemono-poc-runner` runtime and `tm-weekly-trigger` scheduler identities. Additional mutation rights are conditional on exactly three GCS objects: `state/current.json`, `state/collection-lock.json`, and `state/realpro-acquisition-lock.json`. The runtime can read Ulucks job execution status; it cannot change the Ulucks Job through that read-only binding. The trigger can invoke the RealPro Job. Existing creator/viewer and RealPro Secret accessor bindings are reused. No credential value, Cookie, token, login screenshot or private PDF belongs in GitHub.

Container builds overlay only the listed RealPro Python modules on the digest-pinned deployed main runtime. Do not rebuild Ulucks or dispatch an Ulucks collection as part of RealPro deployment. A future change to the imported runtime must be deliberate and regression-checked.

The scheduled all-company run on 2026-10-26 has not happened at implementation time. Enabled configuration and representative proof must never be reported as all-company collection success.

## Representative production result

`tatemono-realpro-weekly-j6kqc` succeeded using runtime code `4ce636ecd6aee138dd3b25182d1c63480ebf8e91`. Acquisition/integration release: `20261024T143125Z-459011014884`.

| Metric | Verified result |
| --- | ---: |
| Fresh Cloud Run catalog | 102 IDs / 99 named links / 3 empty links |
| Acquired companies | 2 |
| Daito Kokura / Apaman Kokura PDF | 69 pages / 14 pages |
| Daito / Apaman parsed rooms | 481 / 136 |
| Parsed / adopted / held / anomaly | 617 / 438 / 178 / 1 |
| Adopted existing / new | 434 / 4 |
| Failed companies / duplicate input rows | 0 / 0 |
| Official buildings | 9,918 → 9,922 |
| Historical listing rows | 67,220 → 67,658 |
| Sale listing rows | 11,907 → 11,907 |
| Public buildings / vacancies | 8,195 / 8,311 |

Original SHA-256:

- `15974`: `68f86b31bfe3fc7ee655d4cca74ceb65464e84a5c303f9ba68eb8661dbb112f4`
- `22452`: `941cf69d63b04f0de96bd5007db105bb26cc3728f8fe3e2ff877232e937e8559`

Two earlier executions stopped before PDF export because the legacy download handler used a builtin `list.append`, which Playwright cannot wrap. Stable function handlers fix that incompatibility; a regression test invokes the real Playwright handler wrapper. Those stopped attempts did not download PDFs or update HEAD. Successful originals and integration receipts are retained in the cycle above; never rerun the source acquisition to verify them.
