# 統合最適化システム - 使用ガイド

## 概要

平常時と故障時を統合した充電ステーション最適化システムです。目的関数をGUIで柔軟にカスタマイズできます。

**目的関数**: `F = objective_function(normal_cost, failure_cost, P)`

## クイックスタート

### 1. GUI起動

```bash
cd /home/oums/Desktop/emates
source .venv/bin/activate
streamlit run src/config/unified_config_gui.py
```

ブラウザが自動で開きます（通常 http://localhost:8501）

### 2. 設定をGUIで調整

- **タブ1 (最適化モード)**: P値を選択（0.0〜1.0）
- **タブ2 (目的関数)**: 目的関数を選択・カスタマイズ
- **タブ3 (基本設定)**: 保存先、トライアル数を設定
- **タブ4 (並列処理)**: Worker数を調整
- **タブ5 (詳細設定)**: 収束判定、Optuna設定
- **タブ6 (プレビュー)**: 設定を確認

### 3. 設定を保存

GUI下部の「💾 設定を保存」ボタンをクリック → `unified_config.json`が生成されます

### 4. 最適化実行（テンプレート）

```bash
python cs_optim_unified.py unified_config.json
```

**注意**: 現在は設定読み込みのテンプレートのみ実装済み。最適化ロジックは今後実装予定です。

---

## 目的関数のカスタマイズ

### 事前定義された目的関数

| 名前 | 数式 | 用途 |
|------|------|------|
| **重み付き和** | `(1-P) * normal + P * failure` | 標準的な方法（デフォルト） |
| **最大値** | `max(normal, failure)` | 最も保守的な設計 |
| **重み付き最大値** | `max((1-P)*normal, P*failure)` | 保守的だが重み考慮 |
| **幾何平均** | `normal^(1-P) * failure^P` | バランス重視 |

### カスタム数式の例

GUI の「目的関数」タブで「カスタム式」を選択し、Python式を入力：

```python
# 例1: ペナルティ付き重み付き和
(1-P) * normal + P * failure + 0.1 * abs(normal - failure)

# 例2: 非線形重み
(1-P**2) * normal + P**2 * failure

# 例3: 条件付き評価
normal if failure < 200 else failure

# 例4: 複雑な組み合わせ
0.3 * normal + 0.5 * failure + 0.2 * max(normal, failure)
```

**使用可能な変数・関数**:
- `normal`: 平常時コスト
- `failure`: 故障時コスト
- `P`: 故障重み（failure_weight）
- `max()`, `min()`, `abs()`: Python組み込み関数

---

## プリセット設定

GUI左サイドバーから選択：

| プリセット | P値 | トライアル数 | 用途 |
|----------|-----|------------|------|
| **クイックテスト** | 0.5 | 10 | 動作確認用 |
| **平常時のみ** | 0.0 | 1000 | コスト最小化 |
| **故障時のみ** | 1.0 | 1000 | ロバスト設計 |
| **バランス型** | 0.5 | 1000 | 標準的な最適化 |
| **堅牢性重視** | 0.8 | 1500 | 故障時重視 |
| **本番環境** | 0.5 | 3000 | 本格的な最適化 |

---

## ファイル構成

```
emates/
├── cs_optim_unified.py              # 統合最適化スクリプト（テンプレート）
├── src/
│   └── config/
│       ├── unified_optimization_config.py  # 設定クラス
│       └── unified_config_gui.py           # Streamlit GUI
└── unified_config.json              # 保存された設定ファイル
```

---

## 設定ファイルの使用

### Pythonコードから読み込み

```python
from pathlib import Path
from src.config.unified_optimization_config import UnifiedOptimizationConfig

# 設定読み込み
config = UnifiedOptimizationConfig.from_json(Path("unified_config.json"))

# パラメータ取得
print(f"故障重み: {config.failure_weight}")
print(f"保存先: {config.save_dir}")
print(f"目的関数: {config.get_objective_formula()}")

# 目的関数の計算
unified_cost = config.calculate_objective(
    normal_cost=100.0,
    failure_cost=150.0
)
print(f"統合コスト: {unified_cost}")
```

### プログラムから作成

```python
# プリセットから作成
config = UnifiedOptimizationConfig.create_preset("balanced")

# カスタマイズ
config.failure_weight = 0.6
config.experiment_name = "my_experiment"
config.total_trials = 500

# カスタム目的関数
from src.config.unified_optimization_config import ObjectiveFunction
config.objective_function = ObjectiveFunction(
    name="custom",
    formula="0.4 * normal + 0.6 * failure",
    description="カスタム重み"
)

# 保存
config.to_json(Path("my_config.json"))
```

---

## トラブルシューティング

### GUI が起動しない

```bash
# Streamlitがインストールされているか確認
pip list | grep streamlit

# インストール
pip install streamlit
```

### 設定ファイルが読み込めない

```python
# JSON構文エラーをチェック
import json
with open("unified_config.json") as f:
    data = json.load(f)  # エラー箇所が表示される
```

### カスタム目的関数がエラー

- GUIの「式をテスト」ボタンで事前確認
- 許可されていない関数（`import`, `os`など）は使用不可
- 変数名は `normal`, `failure`, `P` のみ

---

## 次のステップ

### 1. 最適化ロジックの実装

`cs_optim_unified.py` に以下を追加：

- [ ] `run_normal_scenario()` - 平常時シナリオ実行
- [ ] `run_failure_scenarios()` - 故障時シナリオ実行
- [ ] `evaluate_unified_objective()` - 統合評価
- [ ] `run_parallel_optimization_batch_unified()` - バッチ処理

参考: `cs_optim_fail.py`, `cs_optimization_Optuna copy.py`

### 2. モニタリングGUIの追加（オプション）

実行中の進捗をリアルタイム表示

```bash
streamlit run src/config/monitor_gui.py
```

---

## 参考資料

- **Plan.md**: 詳細な設計ドキュメント
- **cs_optim_fail.py**: 故障時最適化の実装例
- **cs_optimization_Optuna copy.py**: 平常時最適化の実装例
- **src/config/config_gui.py**: 既存GUIの実装

---

## サポート

問題が発生した場合:

1. GUI の「プレビュー」タブで設定を確認
2. `config.validate()` でエラーチェック
3. テスト用プリセット（クイックテスト）で動作確認

---

**最終更新**: 2025年12月13日
