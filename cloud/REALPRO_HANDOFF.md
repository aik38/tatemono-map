# RealPro cloud checkpoint — 2026-10-23

Status: incomplete. No RealPro release has been committed to the official HEAD.
Do not describe parser tests, a built image, or a started Job as collection/publication success.

## Preserved production baseline

- main before work: `33d10349659739808891eae6bd7b2208aa9e162b`.
- Official HEAD: `20261018T190110Z-9aa6143e7cf5`, generation `1792354071251039`.
- Master reference: generation `1792354070414927`, SHA-256 `88eea87aa2cad7e5176863103edbbb9f0b72f6740f8f73f948bbdc515a2a2812`.
- Public reference: generation `1792354071134020`, SHA-256 `250772378e7c8e238549d94d1f30ffc84fd70801aad4a2e75db21776c92f40be`.
- Master: 7,556 buildings, 61,976 rental history rows, 11,907 sale rows.
- Public: 7,550 buildings, 7,000 vacancies.
- Private pinned backups and receipt:
  `gs://tatemono-map-poc-523194690131/deployment-backups/realpro/20261023T113751Z-pinned/`.
  Master/public copies were generation-pinned and size/CRC32C verified.
  Original HEAD and Ulucks Job/Scheduler configurations are retained there.
- Ulucks Scheduler remains Monday 04:00 Asia/Tokyo. Do not modify it.

Never restore this baseline over a later Ulucks release. Every integration must download
the then-current generation, take a new backup, and commit with that exact HEAD CAS.

## Proven observations

Live company link ID `15974` is 大東建託パートナーズ 小倉営業所.
The live seven `input.city_check` values are 40101, 40106, 40107, 40206, 40213, 40621, 40647.
The independent scroll container is `.company_room` with overflow auto.
The PDF action is `img.print_button_image[src="./img/DL_list_company.jpg"]`.
After clicking, `form#company_search` has POST action `common/pdf_list.php`, target `_blank`.
107 town-code checkboxes were selected by the seven city selections.
The local extension did not expose a completed PDF download; do not count that as fresh acquisition.

The supplied 71-page PDF parsed to 503 rows and 334 distinct source name/address pairs.
These are supplied-PDF observations, not production collection or canonical adoption counts.
Fixed the scope heading being misread as a building name and evidence IDs colliding between tables.
Seven source addresses without detailed lot suffixes still raise the existing address warning.
Uncertain matches are private; parser count alone never authorizes publication.

## Authentication evidence and owner gate

Cookie-empty GCP browser sessions observed:

1. RNP: `realnetpro.com/index.php`, `#login_form`, `id` / `pass`, button calls `login_send()`.
2. Observed old-BB banner opens `login.n-create.jp`; store/personal tabs both use
   `input[name=login_id]`, `input[name=password]`, submit button ログイン.
3. The saved Secret's credentials were explicitly rejected by both old-BB account modes.
4. Cloud Run execution `tatemono-realpro-weekly-dnzsd` (image source `c53e2cb7f6ac3af50c15885cb4738b0d7f1f4bf4`)
   completed with `realpro_login_not_confirmed` on the RNP entry; it did not acquire a PDF.

Do not infer that an authentication failure is a consent gate. The owner's supplied
consent/service-start/linkage screenshots document additional possible post-login states;
they have not yet been reached by this GCP execution.

`login_route` explicitly selects `rnp`, `bb_store`, or `bb_personal`; no automatic
three-realm credential retries. `finish_login` distinguishes terms consent and never
clicks agreement. A new agreement requires the owner. Service-start and optional
account-linkage handling remain conditional. Successful post-login branches still
require live validation after credentials work.

Owner registration command (hidden inputs; no credentials in arguments/history):

```sh
python3 cloud/register_realpro_login.py
```

This adds a version to the existing `tm-poc-realpro-login` Secret. Never ask for
passwords in chat, copy Chrome cookies, print Secret values, or persist redirect queries.

## Runtime and resumption

- Independent Job: `tatemono-realpro-weekly`, asia-northeast1.
- It is staged with `--acquire-only`. No RealPro Scheduler has been enabled.
- `tatemono-poc-runner` already reads the RealPro Secret but has only objectCreator/objectViewer
  on this bucket. PDF-only acquisition must not take the global production lease.
- Full integration requires existing get/create/delete/list permissions; the entrypoint
  now checks this before taking a lease. Do not grant broad project roles.
- The first failed proof left lease generation `1792757108572032`, owner
  `20261023T120508Z-21014b67738c`. The operator records its cleanup separately in that
  private-run prefix after checking the completed execution, and removes only that generation.

After successful owner credential registration:

1. Execute the latest staged image once with `--acquire-only`; require fresh PDF evidence.
2. Reuse that acquisition via `--reuse-run RUN_ID`; do not re-download diagnostically.
3. Run guarded integration under a suitable existing identity, first `--dry-run`,
   then against the latest HEAD with the shared collection lease and CAS.
4. Merge the accounting-contract support to main before Pages consumes a RealPro HEAD.
5. Verify actual public JSON and representative HTML against release proof.
6. Only then implement/enable company expansion and weekly collection.

The integration adapter reuses the registry, priorities, public exporter and immutable release
writer. It preserves other current snapshots, existing canonical attributes and historical
rows, retains unresolved prior company units, and rejects unaccounted/duplicate/out-of-scope rows.
