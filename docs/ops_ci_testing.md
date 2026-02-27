# MVP運用における CI / pytest 仕分け

## 結論（先に要点）
- `.github/workflows/pages.yml` は **Pages公開用**。`pytest` は実行しない。
- `.github/workflows/ci.yml` は **PR検証用**。`pull_request` で `pytest -q` を実行する。
- 週次のMVP運用（`run_to_pages.ps1`）に `pytest` は必須ではない。
- ただし、PRを作る週は CI 失敗を分類して対処する。

## 1) Pages workflow の責務
対象: `.github/workflows/pages.yml`

実施内容（抜粋）:
- `data/public/public.sqlite3` の存在確認
- `building_summaries` テーブル存在確認
- `building_summaries` が非空であることを確認
- `dist/` を build
- `dist/index.html` に building-card が存在することを確認
- 禁止語の簡易 grep チェック

> つまり pages.yml は「公開可能な配信物か」のガードであり、テストスイートではない。

## 2) PR CI workflow の責務
対象: `.github/workflows/ci.yml`

実施内容:
- トリガー: `pull_request`
- 依存をインストール
- `python -m pytest -q` を実行

> つまり ci.yml は「変更の品質確認（テスト）」の担当。

## 3) 運用方針（weekly run と PR週）
- **weekly run（運用実行のみ）**:
  - `run_to_pages.ps1` を正とし、PagesのSuccessと公開値確認を優先
  - `pytest` は必須ゲートにしない
- **PRを作る週**:
  - `ci.yml` の失敗を確認し、以下で分類して対処
    - テスト壊れ（実装修正が必要）
    - テストデータ/前提差異（fixture/前提調整が必要）
    - 環境差異（依存・OS差）
  - 「失敗理由を書いて次アクションを決める」までを完了条件にする
