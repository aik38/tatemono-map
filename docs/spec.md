# spec（現行実装契約）

2026-10-19 JST更新。対象は現在のUlucksクラウド経路と共有の建物・公開モデルです。[PLAN](../PLAN.md)、[データフロー](data_flow_and_sources_of_truth.md)、[Cloud](../cloud/README.md)を併読してください。

## 正式正本と派生物

- 本番正本はGCS `state/current.json` がgeneration・SHA-256付きで参照するSQLite正式正本。
- `buildings`はcanonical建物、`listings`/`sale_listings`は募集と履歴、`building_key_aliases`/`building_sources`は同定・由来、`ingest_runs`/`current_ingest_snapshots`は実行と有効スナップショットを管理します。
- `building_summaries`等の集約、公開専用SQLite、検索JSON・HTML・サイトマップは派生物です。公開DBから正本を復元・上書きしません。
- PDF原本・解析結果・private保留記録はGCSのprivate領域に保管する実装です。SQLiteに構造化することは原本廃棄を意味しません。保存期間は未確認です。

## Canonical建物の保護

- 既存ID・canonical名・住所・URL・canonicalタグ・履歴を維持。通常取り込みで既存canonical値を自動上書きしません。
- 建物を再構築・削除せず、募集0件でも公開対象建物ページを残します。
- 正規化名・住所は照合材料であり、文字列一致だけで別canonical IDを確定・統合・検索除外しません。
- aliasは同一建物への対応です。`publication_merge_targets`は明示的aliasと両者の整合する同一性を確認し、矛盾する古いaliasでページを統合しません。

## 採用・保留・公開

- 収集・解析・名寄せ・QC時点で精査し、既存マッチまたは高信頼auto-seedを正式採用します。
- auto-seedは`ingest_master_import`の既存ガードに従います。曖昧・異常行はprivateに保留し、未解決値を確定公開しません。
- 全明細保留となった未採用の仮登録を、正式採用建物と混同しません。raw・review等の証跡を保持します。
- 正式採用建物は原則自動公開。明示的非公開条件は`COALESCE(hidden_from_public,0)<>0`です。
- `publication_ids(master)`で正式正本の非hidden ID集合を決めます。過去の公開DBは既存ID欠落の防止用で、新規公開の許可リストではありません。
- 正当で整合するcanonical aliasによるページ統合は`rendered_ids`に反映します。DB件数とページ件数が異なる場合は、その根拠を確認します。
- 通常週次に人間の追加公開承認を挟みません。保留解決やcanonical修正は別の例外作業です。

## 募集とソース

- 賃貸・分譲は同じcanonical建物に結び、`listings`と`sale_listings`等で別系統に保持します。
- 賃貸基本優先順位はUlucks ＞ RealPro ＞ Mansion Review賃貸。Mansion Review分譲は独立ソースです。
- `effective_rentals`は建物単位で最優先ソースを選択し、複数ソースの項目を任意に混ぜません。優先順位未定義のlegacy行が混在する場合は既存の合成snapshot方針を保つため、全行に一律の順位フィルターが掛かるとは限りません。
- 集約は各ソースの有効なcurrent snapshotを合成します。全履歴を現在募集として合算しません。
- Ulucksクラウドのscopeは`ulucks:<scope-hash>`。`listings.source_kind=ulucks`を維持し、会社・対象範囲を`cloud_scope_bindings`で管理します。
- `cloud_baseline_ownership`や重複管理で確認された対象のみ旧明細と調整します。不明な旧明細・他社履歴・他ソースcurrentを一括削除しません。
- 正常0件は取得画面・件数・証跡で確認した場合のみ。認証失敗、PDF欠落、未対応会社、一部取得失敗を正常0件へ置換しません。
- 全社バッチは安全条件を満たす会社だけのpartial_successを正式保存し得ます。失敗会社の旧snapshotを保持し、失敗会社・利用不可会社・保留行を成功件数と区別します。

## リリース安全性と公開境界

- 正本変更前にバックアップし、generation指定で取得してSHA-256・DB整合性・件数・ID・履歴保持を検証します。
- immutableなmaster/publicを保存してから、期待generationを条件とするCASで正式HEADを更新します。
- collection leaseで収集・公開専用処理の同時実行を防ぎます。正式commitできない失敗runでHEADを切り替えません。
- 公開DBは許可テーブルだけを新規コピーし、`listings`・`raw_sources`・PDF・privateレビュー・認証情報を含めません。
- Pagesは公開専用DBの世代・SHA・件数を検証し、ID集合・集約値を照合します。公開後は実Webのmarker・JSON等を照合します。
- 復旧は現在HEAD/世代と稼働中Jobを再確認し、後発の正常な成果を古いバックアップで巻き戻しません。

実装参照: [public_db.py](../src/tatemono_map/cloud/public_db.py)、[pipeline.py](../src/tatemono_map/cloud/pipeline.py)、[batch.py](../src/tatemono_map/cloud/batch.py)、[storage.py](../src/tatemono_map/cloud/storage.py)、[fetch_public.py](../src/tatemono_map/cloud/fetch_public.py)。本番確認手順は[runbook](runbook.md)に集約します。
