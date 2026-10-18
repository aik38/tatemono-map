# tatemono-map WBS（完全版 / 正本）

## 現行ステータス追記（2026-10-19 JST）

本節を現在の進捗として読み、以下の旧Phase/Backlog本文は当時の計画・DoDの原記録として参照します。旧文の「唯一の正本」は建物同一性の意味に限定し、本番の実体はGCS `state/current.json`が指すSQLite（募集・履歴・snapshotを含む）です。旧Windows手順・PR3将来扱いを現在の未着手タスクに戻しません。

| 工程 | 現在の状態・適用範囲 |
| --- | --- |
| Phase 0 文書入口 | 今回クラウド構成へ更新。旧repo指定Windows一発を現行必須導線にしない |
| Phase 1 canonical / Phase 2 同定 | 既存機能を使用。ID/正式名/住所/URL・alias・由来・履歴を保護 |
| Phase 3 公開 | Ulucks実収集→正本更新→GCS→Pages・実Web照合は実行成功済み。Work Bで非hidden正式採用建物の自動同期へ更新 |
| PR3 auto-seed | 高信頼auto-seedは実装済み。曖昧・異常はprivate保留。旧Low優先の未着手計画ではない |
| Phase 4 品質 | 採用/保留/異常分類・会社別QCは稼働。保留解消は継続課題で、公開の毎週承認を追加しない |
| 通常クラウド週次 | fresh全社判定・北九州全域・月曜04:00 JST設定あり。文書整理時点では2026-10-19 04:00の定刻実行前、無人定刻成功は未実証 |
| RealPro / Mansion Review | 既存取り込み/集約あり。同等GCP週次収集完成は未確認・別工程 |
| Phase 5 地図/導線 | 既存UI/導線を維持。本書更新で新たな実装完了を認定しない |
| Phase 6 売却査定/解体比較/地域拡張 | 将来構想。Ulucks完成と混同しない |

実績・数値は[Cloud文書](../cloud/README.md)、現行契約は[spec](spec.md)、手順は[Runbook](runbook.md)、旧全文の固定保存先は[履歴索引](archive/README.md)を参照します。

## 以下は旧WBSの原記録
> このWBSは「設計思想・実装順・完了条件（DoD）・禁止事項」を固定する憲法。  
> **要約・英語化・削除は禁止**。変更は「追記（差分）」のみ。  
> UI（表示/テンプレ）は変更しない。正本は DB（canonical）。

---

## 0. 共通原則（絶対条件）
### 0.1 目的（プロジェクトの核）
- **Google Maps / Street View と連動した“不動産データベース母艦”**を作る。
- 最初は賃貸（空室）で検証するが、将来的に **売却査定**・**解体比較**などの集客にも拡張する。
- Webは「図鑑/母艦」、刈り取り（申込完結/相談）はLINE等に集約する。

### 0.2 正本（Canonical）
- 正本は **SQLite の `buildings` テーブル**（唯一の正本）。
- `canonical_name` / `canonical_address` は **自動で上書き禁止**（seed/weeklyどちらも）。
- CSVは資産（seed入力・レビュー用）だが正本ではない。

### 0.3 禁止事項（これをやったら失格）
- 旧マスター再構築フローの復活（再生成・CSV正本化・逆流）は禁止。
- 正本（buildings）をCSVに戻す運用は禁止。
- canonical の自動更新は禁止。
- Web出力禁止情報を含めるのは禁止（号室、参照元URL、元付/管理会社、PDF、機微情報）。

### 0.4 週次運用の大原則
- 週次は **「空室だけ更新」「新規建物だけ追加」**。
- 不明は止めずに **review CSVへ出す（処理継続）**。
- **冪等（idempotent）**：同じ入力で2回回しても壊れない・増殖しない。

---

## Phase 0：入口・運用導線の固定（開発が迷子にならない状態）
### Why
- 第三者が読んで理解でき、すぐ運用できる「入口」を作る。
- 開発時の “同期” と “運用” と “初回セットアップ” を混ぜない。

### What
- README を「コピーで使える」構造に固定（日本語、目的、禁止事項、入口コマンド）。
- docs index（docs/README.md）で読む順番を固定。
- WBS/spec/runbook/PLAN の整合を取り、方針の矛盾を排除。
- 開発同期コマンド（repo指定一発）を最上段に固定。
- 生成物（egg-info、tmp、public.sqlite3 等）が誤コミットされない安全策（.gitignore / push安全化）。

### DoD
- README先頭に **repo指定一発**：
  - GitHub→ローカル同期（pull）
  - ローカル状況確認（status）
  - ローカル→GitHub（push）※自動commitはデフォルト無効
- 「setup（初回だけ）」「weekly_update（運用）」は READMEで別セクションに隔離。
- docs/README.md に doc の説明と読む順番がある。
- docs が日本語で読める（英語用語は日本語訳併記）。
- Markdownが1行に潰れたら検知して落とす（ガードが動く）。

---

## Phase 1：正本DB（buildings）確立 + seed を資産化（最重要）
### Why
- 正本（canonical）を確定しない限り、以後すべてが壊れる。

### What
- `buildings` スキーマの確定（canonical_* / normalized_* / created_at/updated_at 等）。
- 正規化モジュール（住所/建物名）を **必ず通る入口**として固定。
- seed（手修正CSV → buildings）投入を **冪等化**（2回流しても増殖しない）。
- alias/evidence（別名・出典）を保持する仕組み（alias一致が最優先で効くこと）。
- canonical_* は上書きしないガード（SQL/UPSERT禁止含む）。
- テスト：seed 2回実行で増殖しない、canonical不変。

### DoD
- seedを2回実行しても buildings件数が増えない。
- canonical_* が1文字も変わらない（差分ゼロ）。
- normalized_* が安定して生成される（同じ入力→同じ出力）。
- alias が効く（alias一致が最優先で紐づく）。

---

## Phase 2：同定（match）と listings 更新運用の確立（週次の心臓）
### Why
- 複数ソースの揺れを吸収し、同一建物に寄せる。

### What
- 入力（PDF/HTML/その他）→標準化（normalize）→ listings 取り込み（ingest）。
- 同定ロジック（優先順位固定）：
  1) alias一致
  2) normalized_address 完全一致
  3) normalized_address一致 + 建物名類似（閾値＋安全装置）
- 不明は review CSV 出力（止めない）：
  - new_buildings
  - suspects（複数候補/差分が僅差/閾値未満）
  - unmatched_listings
- **weekly_update は buildings を再生成しない**（追加のみ）。
- テスト：weekly_update を2回実行しても壊れない（増殖しない）。

### DoD
- weekly_update 2回で buildings が増殖しない。
- 既存建物に listings が正しく紐づく（building_id）。
- 不明は review CSV に必ず出る（処理継続）。
- 同定優先順位がテストで固定されている。

---

## Phase 3：公開物生成（public.sqlite3 / dist）を canonical 由来に一本化（方針の完成）
### Why
- UIを変えずに「中身だけ正しい」状態にする。

### What
- 公開用DB（data/public/public.sqlite3）を **canonical(buildings)+building_summaries（+任意でbuilding_key_aliases）** から生成する（`listings` は公開DBへ含めない）。
  - 互換のため `building_summaries` 等の公開テーブルは維持（UI/静的HTMLが参照している形を壊さない）。
- `publish_public` の流れから legacy（旧マスター再構築由来）を排除・隔離。
- dist（静的HTML）生成は公開DBを参照して作る（禁止情報が混入しない）。
- Windowsの `public.sqlite3` ロック問題：
  - エラーメッセージを明確化（どのプロセスを閉じるべきか）。
  - 可能ならリトライ/待機、ただし無理なら明示的に失敗理由を出す。

### DoD
- weekly_update → publish_public → render.build が完走し、dist が更新される。
- public.sqlite3 が canonical由来で生成される（旧マスター再構築依存ゼロ）。
- Web出力禁止情報が出ない（自動検査またはQC手順がある）。
- ロック時の復旧手順が runbook に明記されている。

---

## Phase 4：運用品質ループ（review消化・品質改善が回る）
### Why
- 自動化は “不明を出す仕組み” と “解決して資産化する仕組み” がセット。

### What
- review CSV の運用手順（誰が/何を/どこに反映するか）を確立。
- 解決したら alias/seed資産へ反映（正本を強化）。
- 品質メトリクス：
  - unmatched率
  - suspects率
  - 新規建物率
- fixture（再現用データ）で回帰を防止。

### DoD
- review を解消する手順が runbook にあり、迷わない。
- 改善が次週に効く（同じ不明が減る）。
- 回帰がテスト/fixtureで検知できる。

---

## Phase 5：地図/ストリートビュー × 導線（母艦としての価値を上げる）
### Why
- 不動産DB母艦の価値は “地図×建物単位” に宿る。

### What
- 建物ページの地図/ストリートビュー連動（UIは維持、埋め込みは段階導入）。
- LINE誘導（問い合わせ/相談）導線の整備（Webで完結させない）。
- 追跡（最低限のイベント/ログ）設計。

### DoD
- 建物単位で「地図→閲覧→相談導線」が成立。
- UIを壊さず、段階的に追加できる設計が固まっている。

---

## Phase 6：拡張（賃貸以外：売却査定/解体比較 など）
### Why
- 賃貸だけでなく、売却/解体も集客できる母艦にする。

### What
- 売却査定の比較導線（建物/エリア単位）
- 解体比較（エリア×業者）導線
- データ項目の拡張（ただし canonical 方針は維持）

### DoD
- 賃貸MVPと競合せず拡張できる（データモデル/導線/運用が衝突しない）。
- KPIが測定できる（獲得/転換）。

---

## Backlog（MVP後の将来タスク）
### PR3：unmatched からの建物自動追加（将来）
- 優先度: **Low（MVPローンチ後）**
- 依存: PR1/PR2/PR2.5 完了、公開反映フロー（weekly_update → publish_public → pages）確立済み
- 目的: unmatched 空室を安全条件付きで buildings に仮登録し、listings へ紐づける
- 設計: 追加条件・重複防止・provenance（`source_kind=vacancy_only` など）・needs_review 分岐を定義
- 実装: ingest に auto-add 分岐を追加し、既存マッチ改善ロジックとは独立に feature flag で制御
- テスト: 正常系（自動追加/紐づけ）・異常系（住所不足/重複）・回帰（誤マッチ増）を fixture で検証
- 検証: `unresolved` 削減効果と人手レビュー増加のトレードオフを週次比較
- ロールバック: flag OFF で即時停止し、PR3 由来の仮登録建物を provenance で抽出して巻き戻し可能にする
