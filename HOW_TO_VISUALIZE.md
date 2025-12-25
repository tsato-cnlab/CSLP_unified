# 可視化ツール 使い方ガイド

最適化結果を平常時・故障時両方で可視化するツールです。

## クイックスタート

```powershell
# 拡張可視化（平常時+故障時）
uv run src/util/visualize_results.py -d <結果ディレクトリ> --extended

# 例
uv run src/util/visualize_results.py -d Z:\output\unified_P00_P00 --extended
```

## オプション一覧

| オプション         | 説明                                      |
| ------------------ | ----------------------------------------- |
| `-d, --result-dir` | **必須** 結果ディレクトリのパス           |
| `-e, --extended`   | 平常時+故障時両方を可視化                 |
| `--optim-config`   | P=0で故障シナリオを追加実行する場合に指定 |
| `--legacy`         | 従来の可視化方式                          |

## 使用例

### 1. 基本的な使い方
```powershell
uv run src/util/visualize_results.py -d Z:\output\exp1 --extended
```

### 2. P=0で故障シナリオも実行したい場合
```powershell
uv run src/util/visualize_results.py -d Z:\output\exp1 --extended --optim-config unified_config.json
```

### 3. 従来の可視化（平常時のみ）
```powershell
uv run src/util/visualize_results.py -d Z:\output\exp1
```

## 出力

```
結果ディレクトリ/
├── optimization_history.png    # 最適化履歴
├── normal/                     # 平常時
│   ├── waiting_time_histogram.png
│   ├── cs_placement_map.png
│   ├── trip_time_comparison.png
│   └── results_summary.txt
└── failure/                    # 故障時（ワーストケース）
    └── （同上）
```

## トラブルシューティング

### 権限エラーが出る場合
Linuxサーバーで実行時、ファイル権限エラーが出る場合：
```bash
sudo chown -R $USER:$USER /home/$USER/Emates/
```

### 故障シナリオ実行がスキップされる場合
- P>0で最適化していれば、故障結果ファイルが既に存在するため追加実行不要
- P=0の場合は `--optim-config` を指定し、サーバー環境で実行
