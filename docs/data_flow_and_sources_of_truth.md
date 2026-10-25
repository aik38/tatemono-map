# 3情報源のクラウド構成とデータ正本

更新: **2026年10月25日 JST**。ここは**システム構成・保存先の唯一の主要説明**です。採否の条件は[spec](spec.md)、運用コマンドは[runbook](runbook.md)に分離します。

## 通常の完全クラウド経路

```text
月曜04:00 Ulucks Cloud Scheduler ─→ tatemono-collection-poc
                                         │ 対象全社・北九州全域PDF
月曜04:05 RealPro Scheduler ───────→ tatemono-realpro-weekly
                                         │ Ulucks終了待ち・福岡県の対象管理会社PDF
月曜04:10 Mansion Review Scheduler → tatemono-mansion-weekly
                                         │ Ulucks/RealPro終了待ち・35市区町村の賃貸/分譲
                                         ▼
                       private GCS（原本/解析/証拠/保留）
                                         ▼
                        品質判定 → canonical名寄せ
                                         ▼
                      正式SQLite（GCS master）＋履歴
                                         ▼
                公開専用SQLite → GCS release / HEAD CAS
                                         ▼
                  GitHub Actions（releaseチェック/ビルド）
                                         ▼
                       GitHub Pages → 実Web照合
```

Schedulerは**起動予定時刻**であり、3Jobをその時刻から同時収集する指示ではありません。RealProは当該週のUlucks実行終了待ち、Mansion Reviewは当該週のUlucks・RealPro実行終了待ち。完了済み失敗のJobがあっても後続が動く実装では、実行状態と結果を必ず区別する。missing/実行中/照会不可は勝手に成功扱いしない。

- GCP project: `tatemono-map` / region: `asia-northeast1` / timezone: `Asia/Tokyo`
- GCS bucket: `tatemono-map-poc-523194690131`
- Scheduler: `tatemono-ulucks-weekly`, `tatemono-realpro-weekly`, `tatemono-mansion-weekly`
- Ulucksは管理会社のfresh判定とPDF取得。RealProは新規ログイン・会社カタログ・対象地域を選んでPDF取得。Mansion Reviewは35市区町村の取得原本をprivate保存し、賃貸・分譲を別系統で取り込む。
- 3系統の実装・週次起動設定は完了。**2026-10-26定刻実行による全対象の独立運用実証は別途確認する。** 会社2社の代表実証と全社実証を混同しない。
- Windows PC、Chrome、ChatGPT Work、手動PDF/ZIP・ローカルSQLiteは通常の経路に含まれない。

## GCSの役割

| 実体 | 保存先・役割 |
| --- | --- |
| **唯一の本番HEAD** | `state/current.json`: 正式master/public・generation・SHA-256・リリースとQCを指す |
| **正式master** | `masters/<run>.sqlite3`: canonical、賃貸・分譲、履歴、alias、ソース別current |
| **公開DB** | `public/releases/<run>/public.sqlite3`: 許可された建物と集約だけ |
| Ulucks原本 | `private-runs/<run>/companies/<id>/pdf/*.pdf` および歴史的な単社path |
| RealPro原本と再開receipt | `private-inputs/realpro/cycles/<cycle>/` と `private-inputs/realpro/originals/<sha256>/` |
| Mansion Review原本と再開receipt | `private-inputs/mansion-review/cycles/<cycle>/` と `private-runs/<run>/` の取得証跡 |
| バックアップ・作業監査 | `backups/<run>.sqlite3`、各`private-runs/<run>/`、必要に応じて専用`deployment-backups/` |
| 公開ページ | GitHub Pagesの静的HTML・JSON・サイトマップ・`cloud_release.json` |

原本は保存後も解析値と別に追跡できる設計です。ただし現存原本総数・バケットのライフサイクル・永久保存期間は未確認のため、無期限保管を保証しません。ファイルの世代とSHA-256で保存・参照を確認します。

## source別の履歴と正式採用

- `buildings`は1建物1canonical IDの恒久資産。`building_sources`/`building_key_aliases`はその由来と同定。
- `listings`は賃貸、`sale_listings`は分譲。`current_ingest_snapshots`はsource/scopeごとの有効取得を選択し、古い履歴を現在募集として数えない。
- `mansion_review_rows`・`mansion_review_scopes`・限定再判定記録がMansion Reviewの原行と採否を保つ。保留行をまとめて公開に流さない。
- 生入力・review・PDFなどprivateな表/原本を公開DBへ転送しない。表示に必要な建物概要だけを生成する。

## 反映・公開・復旧の境界

1. 取得→解析→QC→既存canonicalへの紐付け／安全な新規追加。
2. 最新正式HEADから**世代固定**でmasterを取得し、更新前のバックアップと整合性を検証。
3. master/publicの不変オブジェクトを保存し、collection leaseとgeneration条件付きCASでHEADを安全に切り替える。
4. [Pages Workflow](../.github/workflows/deploy_pages.yml) がmain push・毎時23分の確認・Cloud配置成功・手動dispatchを入口に、公開DBの世代とハッシュを検証し、ページを生成して実Webのrelease markerを照合。
5. 定時チェックでHEADと公開Webに差がなければ重いビルドを省略。文書だけのmain pushでも通常はPages buildの契機になるため、文書整理時は無関係な再配置・再収集を避ける。

新規正式採用の非hidden建物は原則自動公開し、古い公開DBは欠落比較の材料であって新規公開の許可リストではありません。後発の新しい正常HEADが存在する場合は古い成果で巻き戻さない。詳しくは[runbook](runbook.md)。

## ローカルファイルの位置付け

`data/tatemono_map.sqlite3`・`data/canonical/buildings_master.csv`は開発・過去移行・例外補助用。`data/public/public.sqlite3`や`dist/`は公開派生物。ローカルファイルを本番正本扱いせず、通常週次に同期・PC起動を要求しない。
