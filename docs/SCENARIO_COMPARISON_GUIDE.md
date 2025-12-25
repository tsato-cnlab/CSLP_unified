# シナリオ比較可視化ガイド

複数の最適化結果（P値別）を横断的に比較可視化する方法。

---

## クイックスタート

```bash
# 複数ディレクトリを明示的に指定
uv run python -m src.util.visualize_results compare \
    -d "Z:\output\unified_P00" \
    -d "Z:\output\unified_P50" \
    -d "Z:\output\unified_P100" \
    -o "Z:\output\comparison"

# パターンマッチで一括指定
uv run python -m src.util.visualize_results compare \
    --pattern "Z:\output\unified_P*" \
    -o "Z:\output\comparison"
```

---

## コマンドリファレンス

### 単体可視化（single）

```bash
uv run python -m src.util.visualize_results single -d <結果ディレクトリ>
```

| オプション      | 短縮 | 説明                                        |
| --------------- | ---- | ------------------------------------------- |
| `--result-dir`  | `-d` | 結果ディレクトリ（必須）                    |
| `--study-name`  | `-s` | Optuna Study名（自動推測）                  |
| `--result-file` | `-f` | 対象pklファイル（最適トライアルを自動選択） |
| `--config`      | `-c` | 設定ファイルパス                            |
| `--legacy`      |      | レガシーモード                              |

### シナリオ比較（compare）

```bash
uv run python -m src.util.visualize_results compare [オプション] -o <出力先>
```

| オプション     | 短縮 | 説明                               |
| -------------- | ---- | ---------------------------------- |
| `--result-dir` | `-d` | 比較対象ディレクトリ（複数指定可） |
| `--pattern`    | `-p` | globパターン（例: `unified_P*`）   |
| `--output`     | `-o` | 出力先ディレクトリ（必須）         |
| `--no-png`     |      | PNG出力を無効化                    |
| `--no-html`    |      | HTML出力を無効化                   |

---

## 出力ファイル

| ファイル名                      | 説明                           |
| ------------------------------- | ------------------------------ |
| `cost_comparison_boxplot.png`   | P値別コスト箱ひげ図            |
| `cost_comparison_boxplot.html`  | 同上（インタラクティブ）       |
| `cost_breakdown_comparison.png` | コスト内訳（積み上げ棒グラフ） |
| `mean_wait_time_comparison.png` | 平均待ち時間箱ひげ図           |
| `wait_time_95p_comparison.png`  | 95%tile待ち時間箱ひげ図        |
| `wait_time_comparison.html`     | 待ち時間（インタラクティブ）   |

---

## 箱ひげ図の見方

```
     ┌───────────┐
     │           │ ← 第3四分位数（Q3）
   ──┼───────────┼── ← 中央値
     │           │ ← 第1四分位数（Q1）
     └───────────┘
         │
   ─────┬┴┬───── ← ひげ（1.5×IQR）
         ○     ← 外れ値

     ★   ← 平常時（各P値で理論上の最小コスト）
```

- **箱**: 各P値における全故障シナリオのコスト分布
- **★マーカー**: 平常時（故障がない場合）のコスト
- P値が上がるほど故障を重視した最適化になる

---

## ユースケース例

### 感度分析（P=0,10,20,...,100%）

```bash
# 各P値で最適化を実行後
uv run python -m src.util.visualize_results compare \
    --pattern "Z:\output\unified_P*" \
    -o "Z:\output\sensitivity_analysis"
```

### 特定シナリオのみ比較

```bash
# 平常時のみ(P=0%)と故障重視(P=80%)を比較
uv run python -m src.util.visualize_results compare \
    -d "Z:\output\unified_P00" \
    -d "Z:\output\unified_P80" \
    -o "Z:\output\compare_P00_P80"
```

---

## ディレクトリ命名規則

比較機能はディレクトリ名からP値を自動抽出：

```
unified_P00  → P=0%（平常時のみ考慮）
unified_P50  → P=50%（バランス）
unified_P100 → P=100%（故障時のみ考慮）
```

---

## トラブルシューティング

### 「比較データがありません」

- 各ディレクトリに`.pkl`ファイルが存在するか確認
- ファイル名に`_normal`や`_failure`が含まれているか確認

### グラフが生成されない

- Plotlyがインストールされているか確認: `uv pip install plotly`
- matplotlibの日本語フォントが有効か確認
