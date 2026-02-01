# PLAN / WBS（方針固定）

## 目的
- **Google Map / Street View × 自動化バックエンド × LINE刈り取り**を連携し、建物/不動産データの収集〜配信までの流れを最短で実現する。
- UIよりも先に **自動化パイプライン（取得 → 整形 → 保存 → API）** を安定させる。

---

## MVPの定義
### 最初に動くべき（Must）
- APIがローカルで**一発起動**できる（Windows 11 + PowerShell）。
- **SQLite + CRUD** が最低限動く（/health, /buildings など）。
- 位置情報を含む **最小限の建物モデル** が保存できる。
  - ※ Google Maps / Street View のUIは最終形の一部だが、MVPでは任意（後続フェーズ）。

### 最初に動かさない（Won't for MVP）
- 高度なUI/UX（フロントの作り込み）。
- 複数DB/本番相当のスケーリング。
- 大規模な自動スクレイピング（安全性/法務の観点を後回しにしない）。

---

## PDCAループ（1サイクル）
- [ ] **Plan**：Issue化（目的・期待値・Doneの定義を書く）
- [ ] **Do**：実装 → PR作成 → Codexレビュー / 目視確認
- [ ] **Check**：`scripts/sync.ps1` でローカル同期 → `scripts/dev.ps1` で起動確認
- [ ] **Act**：README/PLAN更新（運用が変わったら必ず反映）

---

## 役割分担（迷子防止）
- **README**：手順（実行方法・一発コマンド・運用の入口）
- **PLAN**：方針（目的・MVP定義・PDCA）
- **Issue**：実装タスク（具体的な作業と受け入れ基準）

---

## WBS（最短で動かすための優先順）
1. **起動安定化**：`scripts/dev.ps1` による一発起動
2. **同期/運用**：`scripts/sync.ps1` と `scripts/push.ps1` の運用固定
3. **API最小機能**：/health, /buildings, SQLite
4. **自動化導線**：取得 → 整形 → 保存 → API の最小パイプライン
5. **UI/可視化**：必要最小限の閲覧UI
