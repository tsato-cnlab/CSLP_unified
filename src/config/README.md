# eMATES 最適化 GUI 設定ツール

このディレクトリには、GUIベースの最適化設定ツールが含まれています。

## 起動方法

```bash
cd /home/oums/Desktop/emates
uv run streamlit run src/config/config_gui.py
```

ブラウザで `http://localhost:8501` が開きます。

## 機能

- 最適化パラメータ（バッチサイズ、トライアル数など）をGUIで設定
- 故障シナリオの設定
- 設定をJSONファイルに保存
- 保存した設定ファイルをPythonから読み込み可能

## 使用例

### GUIで設定を作成

1. GUIを起動
2. パラメータを調整
3. 「設定を保存」をクリック → `config.json` が生成

### Pythonスクリプトで設定を読み込み

```python
from pathlib import Path
from src.config.optimization_config import OptimizationConfig

# JSONから設定を読み込み
config = OptimizationConfig.from_json(Path("config.json"))

# パラメータを使用
print(f"バッチサイズ: {config.batch_size}")
print(f"総トライアル数: {config.total_trials}")
```

## ファイル構成

- `optimization_config.py` - dataclassによる設定定義
- `config_gui.py` - Streamlit GUIインターフェース
- `__init__.py` - パッケージ初期化
