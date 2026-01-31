# 建物マップ（Tatemono Map）

北九州市（まずは小倉北区）を対象に、
**Web＝建物ページ（マップ/図鑑）を量産（SEOの土台）**
**LINE＝申込受付（刈り取り）**
を“最小運用”で回すMVP。

---

## MVPの固定方針（ここが憲法）
- Web＝建物マップ（図鑑 / SEO土台）。**申込はしない**
- LINE＝申込受付（入居日確定・初期費用合意・必要書類案内まで）
- 号室はDBに保持しても **Webには出さない**
- 見積（初期費用内訳PDF）は確度が高いユーザーにのみLINEで提示
- 空室ステータスは **{空室あり / 満室} の2値**
- 週2更新 + 最終更新日時で信用を担保（更新失敗でもWeb/LINEは落とさない）
- 引き継ぎは「入居日確定 / 初期費用合意 / 必要書類案内済み」3点セット

---

## 成果物（段階）
- Phase2 PoC：Gmail → URL抽出 → HTML取得 → 最小項目抽出 → DB upsert（週2）
- Web：建物ページテンプレ1枚（Map Embed + 募集サマリー + LINE CTA）
- 失敗時：管理者へLINE通知（落とさない）

---

## ローカル起動（必ず repo 直下で）
### 1) セットアップ
scripts\dev_setup.ps1

### 2) API起動
scripts\run_api.ps1
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/b/demo

### 3) 取り込み（週2想定・今はスタブ）
scripts\run_ingest.ps1

---

## 仕様の正本
- docs/spec.md
- docs/data_contract.md
- docs/runbook.md
