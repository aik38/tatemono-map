# 最小改修に向けた現状調査メモ（2026-03-27）

## 現状理解

### 1) ingest / DB / public DB / build / docs の現状

- ingest の主経路は `scripts/weekly_update.ps1` → `tatemono_map.building_registry.ingest_master_import` → `scripts/publish_public.ps1` という流れ。
- `weekly_update.ps1` は source=`master_import` 固定で取り込み、QCの閾値判定後に `current_ingest_snapshots` を切り替える。
- `publish_public.ps1` は main DB から `buildings` と `building_summaries`（+存在時 `building_key_aliases`）を public DB に丸ごと複製する。
- `run_all_latest.ps1` は週次バッチの統合実行（sync / PDF→CSV / run_to_pages）として動く。
- Source of Truth 方針は README / docs で明示されており、`public.sqlite3` と `dist/` は派生物として直接編集禁止。

### 2) 現行スキーマで今回の要件に関係する主要テーブル

- 既存 canonical 建物: `buildings`
- 由来管理: `building_sources`
- 空室明細: `listings`
- run/snapshot 管理: `ingest_runs`, `current_ingest_snapshots`
- 公開集約: `building_summaries`
- 表記ゆれ吸収: `building_key_aliases`

## 最小改修案

### A. 既存で活かすテーブル

- `buildings`（共通 building_id 管理の中心として継続）
- `building_sources`（source + evidence の追跡を継続）
- `listings`（賃貸明細のSoTとして継続）
- `ingest_runs` / `current_ingest_snapshots`（主経路の運用基盤を継続）
- `building_summaries`（公開用集約を継続。出力列は互換維持）
- `building_key_aliases`（突合品質の維持のため継続）

### B. 新規追加で済ませるテーブル（加算設計）

1. `area_master`
   - 目的: 将来の全国展開を見据えた地域正規化キーを管理
   - 例カラム:
     - `area_code` (PK)
     - `pref_code`, `city_code`, `ward_code`
     - `pref_name`, `city_name`, `ward_name`
     - `normalized_label`
     - `is_active`, `created_at`, `updated_at`

2. `source_priority`
   - 目的: 賃貸データの優先順（ulucks > realpro > mansion_review_chintai）をDB管理
   - 例カラム:
     - `domain`（`rental` / `sale`）
     - `source`（例: ulucks, realpro, mansion_review_chintai, mansion_review_mansion）
     - `priority_rank`（小さいほど優先）
     - `enabled`
     - `effective_from`, `effective_to`
   - 主キー案: `(domain, source)`

3. `sale_listings`
   - 目的: 分譲データを賃貸と物理分離して保持
   - 方針: `listings` を賃貸専用寄りに維持し、分譲は新規テーブルへ
   - 例カラム:
     - `sale_listing_key` (PK)
     - `building_key`
     - `source`, `source_url`, `evidence_id`
     - `price_yen`, `area_sqm`, `layout`
     - `updated_at`, `ingest_run_id`, `fetched_at`

4. `unmatched_queue`
   - 目的: 現在CSVで散在する unmatched/suspects をDBで蓄積
   - 例カラム:
     - `id` (PK)
     - `domain`（rental/sale/facts）
     - `source`
     - `ingest_run_id`
     - `evidence_id`
     - `raw_name`, `raw_address`
     - `normalized_name`, `normalized_address`
     - `reason`
     - `candidate_building_ids`, `candidate_scores`
     - `status`（open/resolved/ignored）
     - `resolved_building_id`, `resolved_at`

5. `qc_run_reports`
   - 目的: weekly QC出力をDBへ蓄積し比較可能にする
   - 例カラム:
     - `id` (PK)
     - `pipeline`（weekly_update/publish_public/run_all_latest）
     - `source`
     - `ingest_run_id`
     - `attached_listings`, `suspects`, `unmatched`
     - `before_count`, `after_count`, `drop_ratio`
     - `qc_mode`, `qc_result`, `message`
     - `created_at`

### C. rental / sale 分離方針

- 原則:
  - 賃貸SoT: `listings`
  - 分譲SoT: `sale_listings`（新規）
- `mansion_review_mansion` は分譲系 source として `sale` ドメインで処理。
- `mansion_review_chintai` は賃貸系 source として `rental` ドメインで処理。
- `building_summaries` 生成は当面互換維持（公開列は増減しない）。
  - 賃貸指標: `listings`（source priority 適用）
  - 分譲指標: `sale_listings`（または建物 facts）を優先

### D. source priority 適用方針（最小）

- 優先順（賃貸）: `ulucks` > `realpro` > `mansion_review_chintai`
- 初期導入は `building_summaries` 集約時のみ適用し、ingest本体の保存ロジックは最小変更。
- 実装方式（最小）:
  - `source_priority` を読み込み
  - 同一 building_key の賃貸候補群を source rank でソート
  - 代表値（age/structure/availability）の計算対象を優先 source ベースで選定

### E. unmatched_queue 方針

- 既存 review CSV 出力は残す（運用互換）
- 追加で同内容を `unmatched_queue` に INSERT（加算）
- 将来的に CSV は監査エクスポート用途へ縮小可能

### F. QCレポート方針

- `weekly_update.ps1` の既存QC判定ロジックはそのまま保持
- 判定値（attached/suspects/unmatched/drop率）を `qc_run_reports` に追記
- 既存ログ + DBレポートの二重化で運用変更を最小化

## 変更対象ファイル一覧

### 変更が必要（実装フェーズに入る場合）

- `src/tatemono_map/db/schema.py`
  - 新規テーブル定義の追加（area_master/source_priority/sale_listings/unmatched_queue/qc_run_reports）
- `src/tatemono_map/normalize/building_summaries.py`
  - source_priority を参照する集約ロジック追加
  - rental/sale の入力系統分離を反映
- `src/tatemono_map/building_registry/ingest_master_import.py`
  - unmatched/suspects のDBキュー保存（CSV併存）
  - category/source の正規化明示
- `src/tatemono_map/building_registry/ingest_building_facts.py`
  - mansion_review_mansion を sale 系として扱う導線を追加
- `scripts/weekly_update.ps1`
  - QC結果のDB保存（判定ロジック自体は温存）
- `scripts/publish_public.ps1`（原則最小）
  - 基本は変更不要だが、将来 public DB に運用メタを出す場合のみ最小変更
- `docs/data_flow_and_sources_of_truth.md`
  - SoTと新規テーブル役割の追記
- `docs/data_contract.md`
  - rental/sale 分離契約と source_priority 契約を追記
- `README.md`
  - 主経路は不変のまま、裏側テーブル追加方針のみ追記

### 変更不要（この方針では維持）

- `scripts/run_all_latest.ps1`（主経路の入口として維持）
- `scripts/run_pdf_zip_latest.ps1`（入力生成系は維持）
- `src/tatemono_map/render/build.py`（見た目/URL非変更のため）
- `templates/` および `templates_v2/`（フロント非変更）
- 公開URL構造（`/`, `/area/...`, `/b/<slug>-<stable_id>.html`。slug不可時は `/b/<stable_id>.html`）

## リスク

1. **source名の揺れリスク**
   - `category` / `source` の命名が `ulucks`,`realpro`,`master` 等で混在しており、priority適用時に取りこぼしが起こり得る。

2. **分譲データ混在リスク**
   - 既存 `buildings` に分譲系属性が既に混在しているため、`sale_listings` 導入時に二重計上/不整合の恐れがある。

3. **snapshot整合性リスク**
   - current snapshot は source単位運用のため、domain（rental/sale）導入時に切替粒度を誤ると公開集計が崩れる。

4. **QCしきい値の誤警報リスク**
   - unmatched_queue化で検知件数の見え方が変わり、既存しきい値との不一致が生じる可能性。

5. **主経路破壊リスク**
   - `weekly_update / publish_public / run_all_latest` に直接大きく手を入れると運用停止リスクが高い。

6. **SoT逸脱リスク**
   - 近道として `public.sqlite3` や `dist` を調整したくなるが、現行方針と衝突する。

## 実装順序（最小）

1. **スキーマ加算のみ導入**
   - 新規5テーブル追加（既存テーブルは非破壊）

2. **source_priority の初期データ投入**
   - rental: ulucks=1, realpro=2, mansion_review_chintai=3
   - sale: mansion_review_mansion=1（必要に応じ拡張）

3. **unmatched_queue / qc_run_reports の書き込み追加**
   - 既存CSV/ログを維持しつつ二重書き

4. **sale_listings への取り込み導線追加**
   - mansion_review_mansion のみ先行で分離

5. **building_summaries に source_priority 反映**
   - まず賃貸代表値の選定ロジックに限定して適用

6. **docs更新（SoT/契約/運用）**
   - README + docs を加筆のみで更新（既存記述は削除しない）

7. **週次主経路の回帰確認**
   - `weekly_update` / `publish_public` / `run_all_latest` の既存成功条件を維持確認
