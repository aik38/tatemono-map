# 現行システム仕様・データ契約

更新: **2026年10月25日 JST**。ここを**採用・同定・公開に関する唯一の主要仕様書**とします。収集順序・保存先は[データフロー](data_flow_and_sources_of_truth.md)、手順は[runbook](runbook.md)。

## 守るべき三原則

1. 既存canonical建物ID・名前・住所・URL・alias・募集履歴を壊さない。
2. 名前や住所が似るだけで建物を統合せず、重複を増やさない。
3. 住所不完全・同定不明・異常・競合は**private保留**し、正確でない情報を公開しない。

## 正式正本とテーブル

- GCS `state/current.json` がgenerationとSHA-256付きで示すmaster SQLiteだけを正式正本とする。
- `buildings`: 恒久的canonical建物。`building_sources`/`building_key_aliases`: 由来・確かな同定。`listings`: 賃貸。`sale_listings`: 分譲販売。`raw_sources`: 非公開の観測原文。
- `ingest_runs`/`current_ingest_snapshots`: 履歴・情報源別の有効な取得。`cloud_scope_bindings`/`cloud_baseline_ownership`: 対象範囲と確認済み旧明細所有範囲。
- Mansion Reviewの`mansion_review_scopes`/`mansion_review_rows`/`mansion_review_building_bindings`と限定再判定台帳は元の証跡・採否を追跡する。元のsnapshotや採用済み履歴を一括置換しない。
- `building_summaries`、公開専用SQLite、検索JSON、HTML、サイトマップは**派生物**。ローカルDB・CSV・git内の公開DBで正本を上書きしない。

## 同定・新規追加・保留

- 既存建物を優先し、証拠のある一意な一致だけ名寄せする。名前・住所の正規化は候補比較であり、それだけでIDの統合・公開除外を決めない。
- 高信頼な新規建物だけauto-seed。既存canonicalの正式名・住所は通常取込で自動上書きしない。棟別表記（A/B棟、号棟、II等）を安易に潰さない。
- Mansion Reviewに限り、`原町別院10-8`のように町名直後の数字から始まる**完全番地**の判定を修正済み。番地欠落、範囲表記、注記付き住所まで無条件採用しない。
- Mansion Reviewに限り、`NestPiece`/`Nest Piece`のような**空白差だけ**を、住所完全一致・canonical一意・他候補や号棟に矛盾がない場合に限って許容。Ulucks・RealProの共通名寄せ規則は緩めない。
- 限定改善の履歴値: 2026-10-25公開時に対象401行を再判定し281行採用・120行保留、新規117棟、追加重複0。これは**結果の記録**であり次週の採用下限ではない。
- 異常・曖昧・未採用の行は原本・evidence・reviewをprivateに保存し、公開しない。失敗・未取得・利用不可を**正常0件にしない**。一部失敗時は成功範囲のみ採用し失敗範囲の旧currentを維持する。

## 賃貸と分譲・公開

- **賃貸優先順位は建物単位で Ulucks ＞ RealPro ＞ Mansion Review賃貸**。`effective_rentals` は優先ソースの有効snapshotだけを選び、別ソースの賃貸行を足し合わせない。順位未定義のlegacy入力の互換扱いは既存実装を維持する。
- `sale_listings` の分譲販売は賃貸と独立。同じ建物が両方に属しても建物IDは一つ。販売掲載数を賃貸空室に加えない。
- 高信頼で正式採用された建物は原則自動公開。`hidden_from_public`だけを明示的非公開の判定材料とする。過去の公開DBを新規公開のホワイトリストにしない。
- 正当なaliasだけでページ統合する。募集0件でも建物ページを維持し、既存のURLを勝手に変更しない。
- 公開用DBは`buildings`/`building_summaries`等の許可した表だけを生成し、号室・生募集明細・参照元URL・管理会社・private PDF・認証情報を公開しない。

## 取込項目・互換契約

- 公式のPDFバッチCSV（v1/16列、UTF-8 BOM）は次の順序を維持する:
  `category,updated_at,building_name,room,address,rent_man,fee_man,layout,floor,area_sqm,age_years,structure,file,page,raw_block,evidence_id`
- **現行の内部インポーター標準は22列**（`ingest_master_import.MASTER_COLUMNS`）。順序は `page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,availability_raw,built_raw,age_years,structure,built_year_month,built_age_years,availability_date,availability_flag_immediate,structure_raw,raw_block,evidence_id`。旧21列（末尾`evidence_id`なし）も受理する。
- 従来のPDFバッチ`final.csv`（上記16列）および旧15列（`page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id`）・旧14列（`evidence_id`なし）も**互換受理**する。16列の`file`は由来追跡の補助。
- `rent_man`/`fee_man`は**万円**、内部賃料は円換算。形式と列順の最終判断はコードの`MASTER_COLUMNS`・`MASTER_COLUMNS_LEGACY`・`MASTER_COLUMNS_WITH_FILE`・`FINAL_SCHEMA`を正とする。
- `age_years`/`structure`が欠損しても取込を継続しNULLで保持。建物集約は欠損を除く最頻値を使い、同率時は`age_years`を中央値、`structure`を辞書順先頭とする既存互換ルールを保つ。建物属性由来の値は賃貸観測値がない場合のフォールバックとなる。
- 比較用住所は都道府県プレフィックス差等を正規化するが、町丁目だけの住所を完全番地と誤認しない。位置情報は任意。空き予定の表示分類は既存実装と整合させ、原文の入居可能日を保持する。
- 戸建行の除外・建物名と号室の分離・QC区分などPDFパーサーの既存規則を維持し、ローカル手動ルートは[専門資料](manual_pdf_ingest.md)として扱う。

## リリース・復旧の非破壊条件

- 更新前に正式master/publicの世代固定取得とバックアップ、SQLite integrity・SHA-256・ID・履歴・情報源別current・公開集約の比較を行う。
- lease・HEAD generationの比較交換（CAS）により上書き競合を防止。後発の正常リリースや別Jobのleaseを壊さない。
- Pages公開は世代・ハッシュ検証済み公開DBを使用し、公開marker・JSON・ID集合・集約値を実Webと比較する。
- 例外修正は[修正台帳の専門資料](building_corrections_csv.md)を参照し、GCS正本への反映は別途バックアップ付きで実施する。

**実装入口:** [取込](../src/tatemono_map/building_registry/ingest_master_import.py) / [Ulucks](../src/tatemono_map/cloud/batch.py) / [RealPro](../src/tatemono_map/cloud/realpro_weekly.py) / [Mansion Review](../src/tatemono_map/cloud/mansion_integrate.py) / [限定再判定](../src/tatemono_map/cloud/mansion_limited.py) / [有効賃貸](../src/tatemono_map/normalize/effective_rentals.py) / [公開DB](../src/tatemono_map/cloud/public_db.py)。
