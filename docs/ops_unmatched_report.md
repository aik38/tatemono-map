# unmatched_report.ps1 運用メモ

## 目的
`tmp/review/unmatched_listings_*.csv` の傾向を、**週次の最小確認**で把握するための簡易集計です。  
パイプライン本体は改造せず、既存CSVを読むだけに限定します。

## 実行方法
```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\unmatched_report.ps1" -RepoPath $REPO
```

任意CSVを指定する場合:
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\unmatched_report.ps1" -RepoPath $REPO -CsvPath "$REPO\tmp\review\unmatched_listings_20260227_090000.csv"
```

## 出力
- 端末出力（集計結果）
- `tmp/review/unmatched_report_latest.txt`（UTF-8）

## 集計内容
- `reason` 上位20
- `normalized_address` 上位10
- `normalized_name` 上位10
- raw `address` 上位10
- raw `name` 上位10

## 仕様メモ
- `-CsvPath` 指定時はそのファイルを優先
- 未指定時は `tmp/review/unmatched_listings_*.csv` の **LastWriteTime 最新**を自動選択
- CSV未存在時はエラー終了せず、メッセージ表示して `exit 0`

## 深追い禁止ルール（重要）
- 週次運用では **reason の偏り確認まで**。
- 個別住所・個別物件名の詳細調査は、必要時のみ別タスク化して実施。
- 毎週の手運用で unmatched を潰し切ろうとしない（最小PDCA優先）。
