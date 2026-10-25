# GCPクラウド — 技術入口

現在の**主要ドキュメントは6ファイル**に集約しました。ここへ同じ運用仕様や数値を重複記載しません。

- 収集対象、3つのCloud Run JobとScheduler、GCSの配置、公開への流れ: [データフロー](../docs/data_flow_and_sources_of_truth.md)
- 運用コマンド、実行状態、異常、バックアップ・切戻し: [本番Runbook](../docs/runbook.md)
- 名寄せ・保留・採用・正本の保護: [spec](../docs/spec.md)
- 開発優先順位と次にすること: [PLAN](../PLAN.md)
- 概要と公開実績: [README](../README.md)

## 専門的な実装・証拠

- Ulucks: [batch.py](../src/tatemono_map/cloud/batch.py) / [pipeline.py](../src/tatemono_map/cloud/pipeline.py)
- RealPro: [realpro_weekly.py](../src/tatemono_map/cloud/realpro_weekly.py) / [2026-10-24実装証拠](REALPRO_AUTOMATION_20261024.md)
- Mansion Review: [mansion_weekly.py](../src/tatemono_map/cloud/mansion_weekly.py) / [mansion_integrate.py](../src/tatemono_map/cloud/mansion_integrate.py) / [mansion_limited.py](../src/tatemono_map/cloud/mansion_limited.py)
- 公開: [fetch_public.py](../src/tatemono_map/cloud/fetch_public.py) / [deploy_pages.yml](../.github/workflows/deploy_pages.yml)

## 整理前の全文

[2026-10-25時点のCloud README](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/cloud/README.md)に、旧PoCの経緯、PDF保存配置、Work Bの公開実績、技術詳細をそのまま保持しています。

その他の古い引継ぎ・監査の原記録は[履歴索引](../docs/archive/README.md)。数値・日時は当時の実績であり、現在のHEADではありません。
