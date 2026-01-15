# 実装計画書: Optuna探索効率化（実効パラメータによる重複スキップ）

## 1. 概要

**課題:** 完全に同一のパラメータが再提案され、シミュレーション結果が同一になる組み合わせを重複計算している。

**解決策:** 「実効パラメータ」で重複判定し、重複時は**別の解を再探索**する（CPUを遊ばせない）。

---

## 2. 現状分析

現在の `set_cs_placement` 関数（`src/util/optimization.py`）:

```python
for i, csid in enumerate(csids):
    ports = trial.suggest_int(f'ports_{i}', 0, 4)
    if ports > 0:
        capacity = trial.suggest_categorical(f'capacity_{i}', [50, 100])
    else:
        capacity = 90  # 非設置なら固定値
```

> **NOTE:** `ports=0` の場合は `capacity` をサジェストしない設計のため、「同一portsで異なるcapacity」の問題は発生しない。ただし、完全に同一の組み合わせが再提案される可能性はあり、その場合のスキップは有効。

---

## 3. 提案する変更

### `cs_optim_unified.py`

#### 3.1. グローバル変数の追加（55行目付近）

```python
# 計算済みの実効パラメータを記録するセット
visited_effective_params: set[tuple] = set()
```

#### 3.2. ヘルパー関数の追加

```python
def get_effective_key(cs_config: dict) -> tuple:
    """CS配置から実効パラメータキーを生成"""
    key_list = []
    for csid, ports, cap in zip(cs_config['csids'], cs_config['ports'], cs_config['cap_kw']):
        if ports > 0:
            key_list.append((csid, ports, cap))
        else:
            key_list.append((csid, 0, -1))
    return tuple(key_list)
```

#### 3.3. `run_parallel_optimization_batch_unified` の変更

トライアル生成ループを `while` ループに変更し、重複時はリトライ:

```diff
+    global visited_effective_params
+    total_skipped = 0
+    MAX_RETRY = 10
+
-    for i in range(outer_parallel):
+    i = 0
+    while i < outer_parallel:
         trial = study.ask()
         config = set_cs_placement(trial)
+
+        effective_key = get_effective_key(config)
+        retry_count = 0
+        while effective_key in visited_effective_params and retry_count < MAX_RETRY:
+            print(f"↩️  Trial {trial.number}: 重複検出、別の解を探索中...")
+            study.tell(trial, state=optuna.trial.TrialState.PRUNED)
+            total_skipped += 1
+            trial = study.ask()
+            config = set_cs_placement(trial)
+            effective_key = get_effective_key(config)
+            retry_count += 1
+
+        visited_effective_params.add(effective_key)
         batch_trials.append(trial)
         batch_configs.append(config)
+        i += 1
```

---

## 4. 検証計画

小規模トライアル（12回程度）で実行し、以下を確認:
1. `↩️ Trial X: 重複検出...` のログが出力されること
2. 累計スキップ数が表示されること

---

## 5. リスク評価

| リスク | 影響度 | 対策 |
|--------|--------|------|
| 正常トライアルの誤スキップ | 高 | シンプルな `ports>0` 判定のみ |
| multiprocessing競合 | 中 | メインプロセスのみで更新 |
