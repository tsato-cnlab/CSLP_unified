# 初期CS配置設定ガイド

## CSVファイルで設定する方法

### 1. CSVファイルの作成

`data/initial_cs_configs.csv` を以下の形式で作成：

```csv
config_name,csid,capacity_kw,ports
均等配置,900000,100,1
均等配置,900002,100,1
集中配置,900000,150,2
集中配置,900002,150,2
```

- **config_name**: 設定の名前（複数行で同じ名前を使うと、それらがまとまって1つの初期配置になります）
- **csid**: 充電ステーションID
- **capacity_kw**: 充電出力（kW、整数）
- **ports**: そのCSのポート数

### 2. unified_config.jsonで指定

```json
{
  "experiment_name": "test",
  "failure_weight": 0.5,
  "total_trials": 100,
  "initial_cs_config_file": "data/initial_cs_configs.csv"
}
```

## JSONファイルに直接記載する方法

unified_config.jsonに直接記載することも可能：

```json
{
  "experiment_name": "test",
  "failure_weight": 0.5,
  "total_trials": 100,
  "initial_cs_configs": [
    {
      "name": "均等配置",
      "placements": [
        [900000, 100, 1],
        [900002, 100, 1],
        [900004, 100, 1],
        [900006, 100, 1]
      ]
    },
    {
      "name": "集中配置",
      "placements": [
        [900000, 150, 2],
        [900002, 150, 2]
      ]
    }
  ]
}
```

- **name**: 設定の名前（ログ出力で確認可能）
- **placements**: `[csid, capacity_kw, ports]` の3要素リスト（capacity_kwは整数）
  - 旧形式の `[csid, ports]` も互換性のため使用可能

## GUIで設定する方法（今後実装予定）

Streamlit GUIに初期CS配置設定タブを追加予定：

1. 「初期配置」タブを選択
2. 配置パターンを追加
3. CSIDとポート数を入力
4. 複数パターンを登録可能
5. 保存してJSON/CSVに出力

## 注意事項

- 初期配置は新規study作成時のみ有効
- 既存studyを継続する場合は適用されない
- CSVとJSON両方を指定した場合、CSV優先
- 設定がない場合はデフォルトの3パターンが自動生成される
- 無効なCSIDは自動的にスキップされる

## デフォルト初期配置

設定なしの場合、以下の3パターンが自動生成：

1. **均等配置**: 全CSに1ポートずつ
2. **少数配置**: 最初の5箇所に1ポートずつ
3. **ランダム配置**: 3-7箇所にランダム配置

## CSVテンプレート

`data/initial_cs_configs.csv` にサンプルファイルを配置済み。
このファイルをコピーして編集してください。
