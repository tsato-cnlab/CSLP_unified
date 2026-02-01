# 充電台数ペナルティ機能 実装レポート

## 実装内容

### 1. 新規関数追加

**calc_uncharged_penalty()** (Line 200-261):
```python
def calc_uncharged_penalty(vehicle_trip: pd.DataFrame) -> float:
    """充電すべきなのに充電していない車両のペナルティ計算"""
    
    # 1. InitialSOC≤20%の車両を特定
    target_vehicles = vehicle_trip[
        (vehicle_trip['InitialSOC'] <= 0.20) & 
        (vehicle_trip['InitialSOC'] >= 0)
    ]
    
    # 2. うち充電していない車両を抽出
    uncharged = target_vehicles[
        (target_vehicles['startChargingTime'] == 0) | 
        (target_vehicles['startChargingTime'].isna())
    ]
    
    # 3. ペナルティ計算
    penalty_yearly = uncharged_count * AVG_CHARGING_TIME * 2 * TIME_VALUE_OF_MONEY * 365
```

### 2. evaluation_total_costs()への統合

**Line 76-83**:
```python
# 未充電車両ペナルティ
uncharged_penalty = calc_uncharged_penalty(vehicle_trip)
uncharged_penalty_discounted = sum(
    (uncharged_penalty / ((1 + DISCOUNT_RATE) ** i)) for i in range(1, YEAR + 1)
)

total_costs = (initial_costs + running_costs_discounted + 
               additional_costs_discounted + waiting_penalty_discounted +
               uncharged_penalty_discounted)  # ← 追加
```

## ペナルティ計算式

```
年間ペナルティ = 未充電台数 × 平均充電時間(0.5h) × 時間価値 × 2倍 × 365日
```

### 具体例

| 未充電台数 | ペナルティ（万円/年） |
|-----------|---------------------|
| 1台 | 40.7万円 |
| 5台 | 203.5万円 |
| 10台 | 407.0万円 |

## 出力例

### 充電率100%の場合
```
充電対象車両: 121 台
未充電車両: 0 台 (充電率100%)
```
→ ペナルティ = 0円

### 未充電がある場合
```
充電対象車両（InitialSOC≤20%）: 121 台
未充電車両: 1 台 (0.8%)
推定損失時間: 0.5 時間
未充電ペナルティ: 40.7 万円/年
```
→ ペナルティ = 40.7万円/年

## Optunaへの影響

### コスト関数の変更

**Before**:
```python
total_costs = initial + running + transport + waiting
```

**After**:
```python
total_costs = initial + running + transport + waiting + uncharged
```

### 最適化への影響

- 充電率が低い設定には自動的にペナルティ
- **99.2%充電率**: 約41万円のペナルティ
- **95%充電率**: 約203万円のペナルティ
- CS配置最適化で充電率100%に近づく

## エラーハンドリング

### InitialSOC列がない場合
```python
if 'InitialSOC' not in vehicle_trip.columns:
    print("Warning: InitialSOC列が見つかりません。未充電ペナルティは0です。")
    return 0.0
```

### データが空の場合
```python
if vehicle_trip is None or vehicle_trip.empty:
    return 0.0
```

## 使用方法

従来通り`evaluation_total_costs()`を呼ぶだけで自動的にペナルティが計算されます：

```python
from src.util.cost_calculator import evaluation_total_costs

total_cost, emates_result = evaluation_total_costs(result_file)
# total_costに未充電ペナルティが含まれる
```

## テスト

### 現在のシミュレーション結果
- 充電対象: 121台
- 充電完了: 120台
- **未充電: 1台**

### 期待される出力
```
充電対象車両（InitialSOC≤20%）: 121 台
未充電車両: 1 台 (0.8%)
推定損失時間: 0.5 時間
未充電ペナルティ: 40.7 万円/年
```

## 修正ファイル

- `/home/oums/Desktop/emates/src/util/cost_calculator.py`
  - 新規関数追加: `calc_uncharged_penalty()` (Line 200-261)
  - 関数修正: `evaluation_total_costs()` (Line 76-83)

## 効果

1. ✅ 充電率を最適化の目的に明示的に組み込み
2. ✅ 未充電車両に対する経済的ダメージを定量化
3. ✅ 待ち行列ペナルティと統一されたロジック
4. ✅ Optunaで自動的に充電率100%を目指す

## 今後の調整

### ペナルティの調整
定数`AVG_CHARGING_TIME`や時間価値の倍率を変更することで、ペナルティの強さを調整可能：

```python
# cost_calculator.py Line 27
AVG_CHARGING_TIME = 0.5  # 平均充電時間（時間）
```

### 閾値の調整
SOC閾値を変更する場合：

```python
# calc_uncharged_penalty() Line 223
SOC_THRESHOLD = 0.20  # 20%から変更可能
```
