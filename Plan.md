# CS最適化統合計画書

## 目的
平常時最適化（`cs_optimization_Optuna copy.py`）と故障時最適化（`cs_optim_fail.py`）を統合し、故障率Pによる重み付け評価を実現する。

**目的関数:**
```
F = (1-P) * 平常時コスト + P * ワースト故障時コスト
```

- P=0: 平常時のみ考慮（既存の`cs_optimization_Optuna copy.py`相当）
- P=1: 故障時のみ考慮（既存の`cs_optim_fail.py`相当）
- 0<P<1: 両方を考慮した堅牢な最適化

---

## コード理解度チェック

### 1. 平常時最適化（`cs_optimization_Optuna copy.py`）の構造

#### 主要関数:
- `run_single_optimization_trial(task_data)`: 単一トライアルの実行
  - CS設定 → シミュレーション → コスト計算
  - 返り値: `evaluation_cost`（平常時の総コスト）

- `run_parallel_optimization_batch(study, batch_size)`: バッチ並列実行
  - `batch_size`個のトライアルを並列処理
  - multiprocessingで複数Worker（1〜batch_size）を使用
  - 結果を`study.tell()`で登録

#### 並列構造:
```
バッチサイズ個のトライアル
├─ Worker 1: Trial N
├─ Worker 2: Trial N+1
├─ Worker 3: Trial N+2
└─ ...
```

#### グローバル変数:
- `SAVE_DIR`: 結果保存先
- `T_HOUR`: シミュレーション時間（26時間）
- `BATCH_SIZE`: 8（並列Worker数）

---

### 2. 故障時最適化（`cs_optim_fail.py`）の構造

#### 主要関数:
- `run_single_failure_scenario(task_data)`: 単一故障シナリオの実行
  - 特定のCS（failure_cs_idx）を故障させる
  - シミュレーション → コスト計算
  - 返り値: 故障時のコストと詳細情報

- `create_failure_scenario_parallel_safe()`: 1トライアルの全故障シナリオ処理
  - 設置されたCS全てについて故障シナリオを生成
  - 各故障シナリオを並列実行（最大8並列）
  - **ワーストケース**のコストを返す

- `run_parallel_optimization_batch_with_failure()`: バッチ並列実行
  - `outer_parallel`個のトライアルを並列処理
  - 各トライアル内で故障シナリオをさらに並列実行

#### 並列構造（2段階）:
```
outer_parallel個のトライアル（ProcessPoolExecutor）
├─ Trial 1 (組み合わせ0): Worker 1-8
│   ├─ 故障シナリオ1（CS[0]故障）: Worker 1
│   ├─ 故障シナリオ2（CS[1]故障）: Worker 2
│   └─ ... （multiprocessing.Pool）
├─ Trial 2 (組み合わせ1): Worker 9-16
│   ├─ 故障シナリオ1: Worker 9
│   └─ ...
└─ ...
```

#### グローバル変数:
- `SAVE_DIR`: 結果保存先
- `T_HOUR`: 26
- `FAILURE_FLAG`: True
- `FAILURE_TIME`: 故障発生時刻（0-26時全時間帯）
- `BATCH_SIZE`: 8
- `OUTER_PARALLEL`: 8（同時処理するトライアル数）

#### 重要な処理:
- `create_failure_info_for_worker()`: 故障情報ファイル生成
- ワーストケースの特定: `max(valid_results, key=lambda x: x['cost'])`
- user_attrへの保存: 故障CS、ワーストコスト、待ち時間等

---

## 統合戦略

### A. アーキテクチャ選択

**推奨: 故障時最適化ベースに平常時評価を追加**

理由:
1. 故障時最適化は既に2段階並列処理を実装済み
2. 平常時評価は1つの追加シナリオとして実装可能
3. P=0の場合も同じコードで処理可能

---

### B. 統合後の処理フロー

```
1. トライアルパラメータ生成（Optuna）
   ↓
2. CS配置決定（set_cs_placement）
   ↓
3. 評価値計算 ← 【統合ポイント】
   ├─ (1-P) × 平常時コスト
   │   └─ run_normal_scenario() ← 新規関数
   ├─ P × ワースト故障時コスト
   │   └─ run_all_failure_scenarios() ← 既存処理
   └─ 合計
   ↓
4. Optunaに結果登録（study.tell）
```

---

## 実装計画

### Phase 1: 新規ファイル作成
**ファイル名:** `cs_optim_unified.py`

### Phase 2: グローバル変数の追加

```python
# 既存
SAVE_DIR = None
T_HOUR = 26
FAILURE_FLAG = True
FAILURE_TIME = list(range(0, T_HOUR+1))

# 新規追加
FAILURE_WEIGHT = 0.5  # 故障率P（0.0〜1.0）
```

### Phase 3: 平常時シナリオ実行関数の実装

```python
def run_normal_scenario(task_data):
    """平常時シナリオを実行（multiprocessing用）

    Args:
        task_data: (cs_config, trial_number, worker_id, save_dir, combination_id)

    Returns:
        dict: {
            'combination_id': int,
            'worker_id': int,
            'cost': float,
            'wait_time_95p': float,
            'results_filepath': str,
            'cs_config': dict
        }
    """
    cs_config, trial_number, worker_id, save_dir, combination_id = task_data

    try:
        # 制約チェック
        if not check_cs_placement(cs_config):
            return {'combination_id': combination_id, 'cost': float('inf'), 'error': 'constraint_violation'}

        # CS設定書き込み
        csList_file = get_paths(worker_id)["csList"]
        update_cs_list(cs_config, csList_file)

        # 平常時シミュレーション実行（故障情報なし）
        only_run_emates(worker_id=worker_id, HOUR=T_HOUR)

        # 結果保存
        results_filename = f"trial_{trial_number}_combo_{combination_id}_normal.pkl"
        results_filepath = os.path.join(save_dir, results_filename)
        save_data_to_pickle(filename=results_filepath, worker_id=worker_id)

        # コスト計算
        evaluation_cost, _ = evaluation_total_costs(result_file=results_filepath)
        wait_time_95p = calculate_95percentile_wait_time(results_filepath)

        return {
            'combination_id': combination_id,
            'worker_id': worker_id,
            'cost': evaluation_cost,
            'wait_time_95p': wait_time_95p,
            'results_filepath': results_filepath,
            'cs_config': cs_config.copy()
        }

    except Exception as e:
        return {'combination_id': combination_id, 'cost': float('inf'), 'error': str(e)}
```

### Phase 4: 統合評価関数の実装

```python
def evaluate_unified_objective(cs_config_dict, trial_number, combination_id, outer_parallel_count):
    """平常時と故障時を統合した目的関数評価

    Returns:
        dict: {
            'trial_number': int,
            'unified_cost': float,  # (1-P)*normal + P*worst_failure
            'normal_cost': float,
            'worst_failure_cost': float,
            'normal_details': dict,
            'failure_details': dict
        }
    """
    print(f"\n=== Trial {trial_number}: 統合評価開始 (P={FAILURE_WEIGHT}) ===")

    # Worker割り当て
    worker_start = combination_id * 9 + 1  # 9 = 1(平常) + 8(故障)

    # ========================================
    # Step 1: 平常時シナリオ実行
    # ========================================
    if FAILURE_WEIGHT < 1.0:  # P<1.0の場合のみ実行
        print(f"📊 平常時シナリオ実行中... (Worker {worker_start})")
        normal_task = (cs_config_dict, trial_number, worker_start, SAVE_DIR, combination_id)
        normal_result = run_normal_scenario(normal_task)
        normal_cost = normal_result['cost']
        print(f"✅ 平常時コスト: {normal_cost:.2f}万円")
    else:
        normal_cost = 0.0
        normal_result = {'cost': 0.0}

    # ========================================
    # Step 2: 故障シナリオ実行
    # ========================================
    if FAILURE_WEIGHT > 0.0:  # P>0.0の場合のみ実行
        print(f"🔥 故障シナリオ実行中...")

        # 既存のcreate_failure_scenario_parallel_safe()を流用
        # ただしWorker IDを調整（worker_start+1 から開始）
        failure_result = create_failure_scenario_parallel_safe(
            cs_config_dict, None, trial_number, outer_parallel_count, combination_id
        )
        worst_failure_cost = failure_result['worst_cost']
        print(f"✅ ワースト故障コスト: {worst_failure_cost:.2f}万円")
    else:
        worst_failure_cost = 0.0
        failure_result = {'worst_cost': 0.0, 'worst_details': {}, 'all_results': []}

    # ========================================
    # Step 3: 統合評価値計算
    # ========================================
    unified_cost = (1 - FAILURE_WEIGHT) * normal_cost + FAILURE_WEIGHT * worst_failure_cost

    print(f"📊 統合評価結果:")
    print(f"   平常時コスト: {normal_cost:.2f}万円 (重み: {1-FAILURE_WEIGHT:.2f})")
    print(f"   故障時コスト: {worst_failure_cost:.2f}万円 (重み: {FAILURE_WEIGHT:.2f})")
    print(f"   統合コスト: {unified_cost:.2f}万円")

    return {
        'trial_number': trial_number,
        'unified_cost': unified_cost,
        'normal_cost': normal_cost,
        'worst_failure_cost': worst_failure_cost,
        'normal_details': normal_result,
        'failure_details': failure_result
    }
```

### Phase 5: バッチ処理関数の修正

```python
def run_parallel_optimization_batch_unified(study, batch_size, outer_parallel):
    """統合版並列バッチ最適化

    変更点:
    1. Worker数計算: 各トライアルで9個必要（平常1 + 故障8）
    2. 評価関数: evaluate_unified_objective()を呼び出し
    3. user_attr: 平常時と故障時の両方の情報を保存
    """
    print(f"\n🔥 統合最適化バッチ処理開始 (P={FAILURE_WEIGHT})")

    # トライアル生成（既存と同じ）
    batch_trials = []
    batch_configs = []
    for i in range(outer_parallel):
        trial = study.ask()
        config = set_cs_placement(trial)
        batch_trials.append(trial)
        batch_configs.append(config)

    # Worker数計算: 9 × outer_parallel
    max_workers_needed = outer_parallel * 9
    print(f"🖥️  必要Worker数: {max_workers_needed} (平常{outer_parallel} + 故障{outer_parallel*8})")

    # 環境構築
    prepare_parallel_environment(batch_configs[0], parallel_count=outer_parallel, batch_size=9)

    # 並列評価実行
    batch_results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=outer_parallel) as executor:
        future_to_data = {}

        for i, (trial, config) in enumerate(zip(batch_trials, batch_configs)):
            future = executor.submit(
                evaluate_unified_objective,
                config, trial.number, i, outer_parallel
            )
            future_to_data[future] = (trial, config, i)

        # 結果収集
        for future in concurrent.futures.as_completed(future_to_data):
            trial, config, combination_id = future_to_data[future]
            result = future.result()
            batch_results.append((trial, config, result))

    # Optunaに登録
    for trial, config, result in batch_results:
        unified_cost = result['unified_cost']

        # user_attr設定
        trial.set_user_attr('failure_weight', FAILURE_WEIGHT)
        trial.set_user_attr('normal_cost', result['normal_cost'])
        trial.set_user_attr('worst_failure_cost', result['worst_failure_cost'])
        trial.set_user_attr('unified_cost', unified_cost)

        # 故障時詳細（既存）
        if result['failure_details']:
            failure_details = result['failure_details'].get('worst_details', {})
            trial.set_user_attr('worst_failure_cs', failure_details.get('failure_cs_idx', -1))
            trial.set_user_attr('worst_wait_time_95p', failure_details.get('wait_time_95p', 0))

        # 平常時詳細（新規）
        if result['normal_details']:
            normal_details = result['normal_details']
            trial.set_user_attr('normal_wait_time_95p', normal_details.get('wait_time_95p', 0))

        # CS配置情報（既存）
        active_cs_info = []
        for i, (csid, ports, cap) in enumerate(zip(config['csids'], config['ports'], config['cap_kw'])):
            if ports > 0:
                active_cs_info.append({
                    'csid': csid,
                    'ports': ports,
                    'capacity_kw': cap
                })
        trial.set_user_attr('active_cs_config', active_cs_info)
        trial.set_user_attr('total_active_cs', len(active_cs_info))
        trial.set_user_attr('total_ports', sum(cs['ports'] for cs in active_cs_info))

        # 統合コストでstudyに登録
        study.tell(trial, unified_cost)

    return len(batch_results)
```

### Phase 6: 故障シナリオ関数の修正

**変更箇所:** `create_failure_scenario_parallel_safe()`内のWorker ID割り当て

```python
def create_failure_scenario_parallel_safe(cs_config_dict, trial_params, trial_number, outer_parallel_count, combination_id):
    # ... 既存コード ...

    # 【修正】Worker割り当て: 平常時用に1個シフト
    worker_start = combination_id * 9 + 2  # +2 = +1(平常時分) + 1(1-indexed)
    print(f"Worker割り当て（故障時）: {worker_start}-{worker_start + 7}")

    # タスクデータ準備
    task_data_list = []
    for i, failure_cs_idx in enumerate(installed_cs_indices):
        worker_id = worker_start + (i % 8)
        task_data = (cs_config_dict, failure_cs_idx, trial_number, worker_id, SAVE_DIR, combination_id)
        task_data_list.append(task_data)

    # ... 残りは既存と同じ ...
```

### Phase 7: メイン実行部の修正

```python
if __name__ == "__main__":
    # グローバル変数初期化
    current_time = datetime.now().strftime('%Y%m%d_%H%M')

    # 【新規】故障率P設定
    FAILURE_WEIGHT = 0.5  # 0.0〜1.0 で調整

    SAVE_DIR = f"/srv/samba/share/output/{current_time}_unified_P{int(FAILURE_WEIGHT*100):02d}"
    os.makedirs(SAVE_DIR, exist_ok=True)

    # 並列処理設定
    BATCH_SIZE = 8
    OUTER_PARALLEL = 8
    TOTAL_TRIALS = 1000

    print(f"📂 結果保存先: {SAVE_DIR}")
    print(f"⚙️ 故障率P: {FAILURE_WEIGHT}")
    print(f"📊 目的関数: F = {1-FAILURE_WEIGHT:.2f}×平常時 + {FAILURE_WEIGHT:.2f}×故障時")

    # Study作成
    db_path = os.path.join(SAVE_DIR, 'optuna_study_unified.db')
    study = optuna.create_study(...)

    # 【修正】統合版バッチ処理を呼び出し
    run_optimization_with_parallel_batches_unified(
        study,
        total_trials=TOTAL_TRIALS,
        batch_size=BATCH_SIZE,
        outer_parallel=OUTER_PARALLEL,
        timeout=TIMEOUT,
        convergence_patience=CONVERGENCE_PATIENCE,
        convergence_threshold=CONVERGENCE_THRESHOLD
    )
```

---

## Worker ID 割り当て設計

### 従来（故障時のみ）:
```
組み合わせ0: Worker 1-8  (故障シナリオ8個)
組み合わせ1: Worker 9-16 (故障シナリオ8個)
...
```

### 統合後:
```
組み合わせ0:
  - Worker 1: 平常時
  - Worker 2-9: 故障シナリオ8個
組み合わせ1:
  - Worker 10: 平常時
  - Worker 11-18: 故障シナリオ8個
...

計算式:
  平常時Worker ID = combination_id × 9 + 1
  故障時Worker ID = combination_id × 9 + 2 〜 combination_id × 9 + 9
```

---

## ファイル整理・削除戦略

### P < 1.0 の場合
- 保存: 平常時pkl、ワースト故障時pkl
- 削除: その他の故障シナリオpkl

### P = 1.0 の場合
- 保存: ワースト故障時pkl
- 削除: その他の故障シナリオpkl（平常時は実行しない）

### P = 0.0 の場合
- 保存: 平常時pkl
- 削除: なし（故障時は実行しない）

---

## テストシナリオ

### Test 1: P=0 (平常時のみ)
- 期待: `cs_optimization_Optuna copy.py`と同じ結果
- 検証: Worker 1のみ使用、故障シナリオなし

### Test 2: P=1 (故障時のみ)
- 期待: `cs_optim_fail.py`と同じ結果
- 検証: Worker 2-9使用、平常時シナリオなし

### Test 3: P=0.5 (両方考慮)
- 期待: 平常時と故障時のバランス
- 検証: Worker 1-9全て使用、統合コストが正しく計算される

---

## リスクと対策

### Risk 1: Worker数不足によるリソース競合
**対策:** `prepare_parallel_environment()`で9×outer_parallel分の環境を確保

### Risk 2: Optunaのトライアル状態管理エラー
**対策:** user_attr設定をstudy.tell()の前に完了させる（既存コード参照）

### Risk 3: メモリ使用量増加
**対策:**
- P=0またはP=1の場合は不要なシナリオをスキップ
- 結果ファイルの即時削除（バックグラウンドスレッド）

### Risk 4: 実行時間の増加
**影響:** P<1かつP>0の場合、実行時間が最大約1.1倍に
**対策:** outer_parallel数を調整してCPU使用率を最適化

---

## まとめ

### 主要な変更点
1. **新規関数**: `run_normal_scenario()`, `evaluate_unified_objective()`
2. **修正関数**: `create_failure_scenario_parallel_safe()`（Worker ID）, バッチ処理関数
3. **新規グローバル変数**: `FAILURE_WEIGHT`
4. **Worker数**: 8 → 9（平常1 + 故障8）

### 実装優先度
1. ✅ Phase 1-2: ファイル作成、グローバル変数
2. ✅ Phase 3: 平常時シナリオ関数
3. ✅ Phase 4: 統合評価関数
4. ✅ Phase 5-6: バッチ処理とWorker ID調整
5. ✅ Phase 7: メイン実行部

### 期待される効果
- **柔軟性**: Pを変えることで様々な最適化方針を試せる
- **堅牢性**: 0<P<1で平常時と故障時の両方を考慮
- **後方互換性**: P=0またはP=1で既存コードと同等の動作

---

## リファクタリング案

### 1. 設定クラスの導入

**問題点:** グローバル変数が多数存在し、スコープ管理が困難

**提案:** 設定を一元管理するdataclassを導入

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass
class OptimizationConfig:
    """最適化実行の設定を管理"""
    # ディレクトリ設定
    save_dir: Path

    # シミュレーション設定
    t_hour: int = 26

    # 故障シナリオ設定
    failure_flag: bool = True
    failure_weight: float = 0.5  # P値（0.0〜1.0）

    # 並列処理設定
    batch_size: int = 8
    outer_parallel: int = 8
    workers_per_trial: int = 9  # 平常1 + 故障8
    failure_workers_per_trial: int = 8

    # 最適化設定
    total_trials: int = 1000
    timeout: int = 60 * 60 * 24
    convergence_patience: int = 100
    convergence_threshold: float = 0.001

    @property
    def failure_time(self) -> list[int]:
        """故障発生時刻のリスト"""
        return list(range(0, self.t_hour + 1))

    @property
    def normal_weight(self) -> float:
        """平常時の重み (1-P)"""
        return 1.0 - self.failure_weight

    def get_worker_range(self, combination_id: int) -> tuple[int, int]:
        """組み合わせIDからWorkerの範囲を計算

        Returns:
            (normal_worker_id, failure_worker_start)
        """
        base = combination_id * self.workers_per_trial + 1
        return base, base + 1

    def should_run_normal(self) -> bool:
        """平常時シナリオを実行すべきか"""
        return self.failure_weight < 1.0

    def should_run_failure(self) -> bool:
        """故障時シナリオを実行すべきか"""
        return self.failure_weight > 0.0

# 使用例
config = OptimizationConfig(
    save_dir=Path(f"/srv/samba/share/output/{current_time}_unified_P50"),
    failure_weight=0.5
)
```

**メリット:**
- 設定の一元管理
- 型安全性の向上
- プロパティで計算値を提供
- テストしやすい

---

### 2. 結果クラスの導入

**問題点:** 辞書型での結果受け渡しは型安全性が低く、キー名のタイポリスクがある

**提案:** 結果を表すdataclassを導入

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ScenarioResult:
    """単一シナリオの実行結果"""
    combination_id: int
    worker_id: int
    cost: float
    wait_time_95p: float = 0.0
    results_filepath: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        """有効な結果かどうか"""
        return self.cost != float('inf') and self.error is None

@dataclass
class FailureScenarioResults:
    """全故障シナリオの結果"""
    trial_number: int
    worst_cost: float
    worst_details: dict = field(default_factory=dict)
    all_results: list[dict] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.worst_cost != float('inf')

@dataclass
class UnifiedEvaluationResult:
    """統合評価の結果"""
    trial_number: int
    unified_cost: float
    normal_cost: float
    worst_failure_cost: float
    normal_details: Optional[ScenarioResult] = None
    failure_details: Optional[FailureScenarioResults] = None

    def to_user_attrs(self, config: OptimizationConfig) -> dict:
        """Optuna user_attrs用の辞書に変換"""
        attrs = {
            'failure_weight': config.failure_weight,
            'normal_cost': self.normal_cost,
            'worst_failure_cost': self.worst_failure_cost,
            'unified_cost': self.unified_cost,
        }

        if self.normal_details:
            attrs['normal_wait_time_95p'] = self.normal_details.wait_time_95p

        if self.failure_details and self.failure_details.worst_details:
            attrs['worst_failure_cs'] = self.failure_details.worst_details.get('failure_cs_idx', -1)
            attrs['worst_wait_time_95p'] = self.failure_details.worst_details.get('wait_time_95p', 0)

        return attrs
```

**メリット:**
- 型安全性の向上
- IDEの補完が効く
- メソッドで処理をカプセル化
- バリデーションが容易

---

### 3. Worker ID 計算の抽象化

**問題点:** Worker IDの計算ロジックが散在し、マジックナンバーが多い

**提案:** Worker管理クラスを導入

```python
from dataclasses import dataclass

@dataclass
class WorkerAllocator:
    """Worker IDの割り当てを管理"""
    workers_per_trial: int = 9  # 平常1 + 故障8
    failure_workers: int = 8

    def get_normal_worker_id(self, combination_id: int) -> int:
        """平常時シナリオ用のWorker IDを取得"""
        return combination_id * self.workers_per_trial + 1

    def get_failure_worker_range(self, combination_id: int) -> range:
        """故障時シナリオ用のWorker ID範囲を取得"""
        start = combination_id * self.workers_per_trial + 2
        return range(start, start + self.failure_workers)

    def get_failure_worker_id(self, combination_id: int, scenario_idx: int) -> int:
        """特定の故障シナリオ用のWorker IDを取得"""
        base = combination_id * self.workers_per_trial + 2
        return base + (scenario_idx % self.failure_workers)

    def get_total_workers(self, num_combinations: int) -> int:
        """必要な総Worker数を計算"""
        return num_combinations * self.workers_per_trial

# 使用例
allocator = WorkerAllocator()
normal_worker = allocator.get_normal_worker_id(combination_id=0)  # 1
failure_workers = list(allocator.get_failure_worker_range(combination_id=0))  # [2, 3, ..., 9]
```

**メリット:**
- Worker ID計算ロジックの一元化
- マジックナンバーの排除
- テストしやすい
- 将来的なWorker数変更に対応しやすい

---

### 4. シナリオ実行の抽象化

**問題点:** 平常時・故障時の実行ロジックに重複が多い

**提案:** 共通基底クラスとStrategy パターン

```python
from abc import ABC, abstractmethod
from typing import Protocol

class ScenarioExecutor(ABC):
    """シナリオ実行の基底クラス"""

    def __init__(self, config: OptimizationConfig):
        self.config = config

    @abstractmethod
    def setup_environment(self, cs_config: dict, worker_id: int) -> None:
        """実行環境のセットアップ"""
        pass

    @abstractmethod
    def execute_simulation(self, worker_id: int) -> None:
        """シミュレーション実行"""
        pass

    def run(self, task_data: tuple) -> ScenarioResult:
        """シナリオ実行の共通フロー"""
        cs_config, trial_number, worker_id, save_dir, combination_id = task_data

        try:
            # 制約チェック
            if not check_cs_placement(cs_config):
                return self._create_error_result(combination_id, 'constraint_violation')

            # 環境セットアップ
            self.setup_environment(cs_config, worker_id)

            # シミュレーション実行
            self.execute_simulation(worker_id)

            # 結果保存・評価
            return self._save_and_evaluate(
                trial_number, worker_id, save_dir, combination_id, cs_config
            )

        except Exception as e:
            return self._create_error_result(combination_id, str(e))

    def _create_error_result(self, combination_id: int, error: str) -> ScenarioResult:
        """エラー結果を作成"""
        return ScenarioResult(
            combination_id=combination_id,
            worker_id=-1,
            cost=float('inf'),
            error=error
        )

    @abstractmethod
    def _get_results_filename(self, trial_number: int, combination_id: int) -> str:
        """結果ファイル名を取得"""
        pass

    def _save_and_evaluate(self, trial_number, worker_id, save_dir,
                          combination_id, cs_config) -> ScenarioResult:
        """結果の保存と評価"""
        filename = self._get_results_filename(trial_number, combination_id)
        filepath = os.path.join(save_dir, filename)
        save_data_to_pickle(filename=filepath, worker_id=worker_id)

        cost, _ = evaluation_total_costs(result_file=filepath)
        wait_time = calculate_95percentile_wait_time(filepath)

        return ScenarioResult(
            combination_id=combination_id,
            worker_id=worker_id,
            cost=cost,
            wait_time_95p=wait_time,
            results_filepath=filepath
        )


class NormalScenarioExecutor(ScenarioExecutor):
    """平常時シナリオの実行"""

    def setup_environment(self, cs_config: dict, worker_id: int) -> None:
        csList_file = get_paths(worker_id)["csList"]
        update_cs_list(cs_config, csList_file)
        # 故障情報は作成しない

    def execute_simulation(self, worker_id: int) -> None:
        only_run_emates(worker_id=worker_id, HOUR=self.config.t_hour)

    def _get_results_filename(self, trial_number: int, combination_id: int) -> str:
        return f"trial_{trial_number}_combo_{combination_id}_normal.pkl"


class FailureScenarioExecutor(ScenarioExecutor):
    """故障時シナリオの実行"""

    def __init__(self, config: OptimizationConfig, failure_cs_idx: int):
        super().__init__(config)
        self.failure_cs_idx = failure_cs_idx

    def setup_environment(self, cs_config: dict, worker_id: int) -> None:
        # 故障情報作成
        create_failure_info_for_worker(
            cs_config, self.failure_cs_idx, worker_id,
            FAILURE_TIME=self.config.failure_time,
            file_write_lock=file_write_lock
        )

        # CS設定書き込み
        csList_file = get_paths(worker_id)["csList"]
        update_cs_list(cs_config, csList_file)

    def execute_simulation(self, worker_id: int) -> None:
        only_run_emates(worker_id=worker_id, HOUR=self.config.t_hour)

    def _get_results_filename(self, trial_number: int, combination_id: int) -> str:
        return f"trial_{trial_number}_combo_{combination_id}_failure_{self.failure_cs_idx}.pkl"

# 使用例
def run_normal_scenario(task_data, config):
    executor = NormalScenarioExecutor(config)
    return executor.run(task_data)

def run_failure_scenario(task_data, config, failure_cs_idx):
    executor = FailureScenarioExecutor(config, failure_cs_idx)
    return executor.run(task_data)
```

**メリット:**
- 共通処理の一元化
- DRY原則の遵守
- 新しいシナリオタイプの追加が容易
- 単体テストが書きやすい

---

### 5. 評価関数の分割

**問題点:** `evaluate_unified_objective()`が長く、責任が多い

**提案:** 単一責任の原則に基づいて分割

```python
class UnifiedEvaluator:
    """統合評価を管理するクラス"""

    def __init__(self, config: OptimizationConfig, allocator: WorkerAllocator):
        self.config = config
        self.allocator = allocator

    def evaluate(self, cs_config_dict: dict, trial_number: int,
                 combination_id: int) -> UnifiedEvaluationResult:
        """統合評価を実行"""
        print(f"\n=== Trial {trial_number}: 統合評価開始 (P={self.config.failure_weight}) ===")

        # 平常時評価
        normal_result = self._evaluate_normal(
            cs_config_dict, trial_number, combination_id
        )

        # 故障時評価
        failure_result = self._evaluate_failures(
            cs_config_dict, trial_number, combination_id
        )

        # 統合コスト計算
        unified_cost = self._calculate_unified_cost(
            normal_result.cost if normal_result else 0.0,
            failure_result.worst_cost if failure_result else 0.0
        )

        return UnifiedEvaluationResult(
            trial_number=trial_number,
            unified_cost=unified_cost,
            normal_cost=normal_result.cost if normal_result else 0.0,
            worst_failure_cost=failure_result.worst_cost if failure_result else 0.0,
            normal_details=normal_result,
            failure_details=failure_result
        )

    def _evaluate_normal(self, cs_config: dict, trial_number: int,
                        combination_id: int) -> Optional[ScenarioResult]:
        """平常時シナリオを評価"""
        if not self.config.should_run_normal():
            return None

        worker_id = self.allocator.get_normal_worker_id(combination_id)
        print(f"📊 平常時シナリオ実行中... (Worker {worker_id})")

        task_data = (cs_config, trial_number, worker_id,
                    str(self.config.save_dir), combination_id)
        result = run_normal_scenario(task_data, self.config)

        print(f"✅ 平常時コスト: {result.cost:.2f}万円")
        return result

    def _evaluate_failures(self, cs_config: dict, trial_number: int,
                          combination_id: int) -> Optional[FailureScenarioResults]:
        """故障時シナリオを評価"""
        if not self.config.should_run_failure():
            return None

        print(f"🔥 故障シナリオ実行中...")

        result = create_failure_scenario_parallel_safe(
            cs_config, None, trial_number,
            self.config.outer_parallel, combination_id
        )

        print(f"✅ ワースト故障コスト: {result['worst_cost']:.2f}万円")
        return FailureScenarioResults(
            trial_number=trial_number,
            worst_cost=result['worst_cost'],
            worst_details=result['worst_details'],
            all_results=result['all_results']
        )

    def _calculate_unified_cost(self, normal_cost: float,
                               failure_cost: float) -> float:
        """統合コストを計算"""
        unified = (self.config.normal_weight * normal_cost +
                  self.config.failure_weight * failure_cost)

        print(f"📊 統合評価結果:")
        print(f"   平常時コスト: {normal_cost:.2f}万円 (重み: {self.config.normal_weight:.2f})")
        print(f"   故障時コスト: {failure_cost:.2f}万円 (重み: {self.config.failure_weight:.2f})")
        print(f"   統合コスト: {unified:.2f}万円")

        return unified
```

**メリット:**
- 各メソッドが単一の責任を持つ
- テストしやすい
- 読みやすい
- 依存関係が明確

---

### 6. 型ヒントの追加

**問題点:** 型情報が不足しており、IDEのサポートが不十分

**提案:** 包括的な型ヒントの追加

```python
from typing import Tuple, List, Dict, Optional, Callable
from pathlib import Path
import optuna

def run_single_failure_scenario(
    task_data: Tuple[dict, int, int, int, Path, int]
) -> Dict[str, any]:
    """単一の故障シナリオを実行

    Args:
        task_data: (cs_config, failure_cs_idx, trial_number,
                   worker_id, save_dir, combination_id)

    Returns:
        故障シナリオの実行結果を含む辞書
    """
    ...

def run_parallel_optimization_batch_unified(
    study: optuna.Study,
    batch_size: int,
    outer_parallel: int,
    config: OptimizationConfig
) -> int:
    """統合版並列バッチ最適化

    Args:
        study: Optuna study オブジェクト
        batch_size: バッチサイズ（未使用、互換性のため保持）
        outer_parallel: 並列実行するトライアル数
        config: 最適化設定

    Returns:
        登録されたトライアル数
    """
    ...
```

---

### 7. ロギングの改善

**問題点:** print文が散在し、ログレベルの制御ができない

**提案:** structuredロギングの導入

```python
import logging
from typing import Any

class OptimizationLogger:
    """最適化用の構造化ロガー"""

    def __init__(self, name: str, save_dir: Path):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        # ファイルハンドラ
        fh = logging.FileHandler(save_dir / 'optimization.log')
        fh.setLevel(logging.DEBUG)

        # コンソールハンドラ
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        # フォーマッター
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

    def log_trial_start(self, trial_number: int, combination_id: int,
                       failure_weight: float) -> None:
        """トライアル開始をログ"""
        self.logger.info(
            f"Trial {trial_number} (組み合わせ{combination_id}) 開始: P={failure_weight}"
        )

    def log_scenario_result(self, scenario_type: str, cost: float,
                           worker_id: int) -> None:
        """シナリオ結果をログ"""
        self.logger.info(
            f"{scenario_type}シナリオ完了: Worker{worker_id}, コスト={cost:.2f}万円"
        )

    def log_unified_result(self, normal_cost: float, failure_cost: float,
                          unified_cost: float, weights: Tuple[float, float]) -> None:
        """統合結果をログ"""
        self.logger.info(
            f"統合評価: 平常{normal_cost:.2f}万円(重み{weights[0]:.2f}) + "
            f"故障{failure_cost:.2f}万円(重み{weights[1]:.2f}) = "
            f"統合{unified_cost:.2f}万円"
        )

    def log_error(self, context: str, error: Exception) -> None:
        """エラーをログ"""
        self.logger.error(f"{context}: {type(error).__name__}: {error}", exc_info=True)

# 使用例
logger = OptimizationLogger('cs_optimization', config.save_dir)
logger.log_trial_start(trial.number, combination_id, config.failure_weight)
```

**メリット:**
- ログレベルによる制御
- ファイル出力による永続化
- 構造化された情報
- デバッグが容易

---

### 8. エラーハンドリングの統一

**問題点:** エラーハンドリングが統一されていない

**提案:** カスタム例外とエラーハンドラの導入

```python
class OptimizationError(Exception):
    """最適化関連のエラー基底クラス"""
    pass

class ConstraintViolationError(OptimizationError):
    """制約違反エラー"""
    pass

class SimulationError(OptimizationError):
    """シミュレーション実行エラー"""
    pass

class WorkerError(OptimizationError):
    """Worker関連エラー"""
    def __init__(self, worker_id: int, message: str):
        self.worker_id = worker_id
        super().__init__(f"Worker {worker_id}: {message}")

def handle_scenario_error(
    error: Exception,
    context: str,
    logger: OptimizationLogger,
    default_result: ScenarioResult
) -> ScenarioResult:
    """シナリオ実行エラーを処理

    Args:
        error: 発生した例外
        context: エラーのコンテキスト
        logger: ロガー
        default_result: デフォルトの結果

    Returns:
        エラー情報を含む結果
    """
    logger.log_error(context, error)

    if isinstance(error, ConstraintViolationError):
        default_result.error = 'constraint_violation'
    elif isinstance(error, SimulationError):
        default_result.error = 'simulation_failed'
    else:
        default_result.error = str(error)

    return default_result
```

---

### 9. テスト容易性の向上

**提案:** 依存性注入とモック可能な設計

```python
class SimulationRunner(Protocol):
    """シミュレーション実行のインターフェース"""
    def run(self, worker_id: int, hour: int) -> None:
        ...

class CostCalculator(Protocol):
    """コスト計算のインターフェース"""
    def calculate(self, result_file: str) -> Tuple[float, Any]:
        ...

class ScenarioExecutorWithDI(ScenarioExecutor):
    """依存性注入対応のシナリオ実行"""

    def __init__(
        self,
        config: OptimizationConfig,
        simulator: SimulationRunner,
        cost_calculator: CostCalculator
    ):
        super().__init__(config)
        self.simulator = simulator
        self.cost_calculator = cost_calculator

    def execute_simulation(self, worker_id: int) -> None:
        self.simulator.run(worker_id, self.config.t_hour)

    def calculate_cost(self, filepath: str) -> float:
        cost, _ = self.cost_calculator.calculate(filepath)
        return cost

# テスト例
class MockSimulator:
    def run(self, worker_id: int, hour: int) -> None:
        pass  # テスト用のモック実装

class MockCostCalculator:
    def calculate(self, result_file: str) -> Tuple[float, Any]:
        return 100.0, None  # 固定値を返す
```

---

### 10. ファイル構造の改善

**提案:** モジュール分割

```
cs_optim_unified/
├── __init__.py
├── config.py              # OptimizationConfig
├── models.py              # 結果クラス (ScenarioResult等)
├── worker_allocator.py    # WorkerAllocator
├── executors/
│   ├── __init__.py
│   ├── base.py           # ScenarioExecutor基底クラス
│   ├── normal.py         # NormalScenarioExecutor
│   └── failure.py        # FailureScenarioExecutor
├── evaluators/
│   ├── __init__.py
│   └── unified.py        # UnifiedEvaluator
├── batch_optimizer.py     # バッチ処理ロジック
├── logging_utils.py       # OptimizationLogger
└── main.py               # エントリーポイント
```

---

## リファクタリング実装の優先順位

### 高優先度（即座に実装すべき）
1. ✅ **設定クラスの導入** - グローバル変数を削減
2. ✅ **Worker ID計算の抽象化** - マジックナンバー排除
3. ✅ **型ヒントの追加** - 型安全性向上

### 中優先度（実装後に適用）
4. ⭐ **結果クラスの導入** - 辞書から型安全なクラスへ
5. ⭐ **評価関数の分割** - 可読性向上
6. ⭐ **ロギングの改善** - デバッグ効率化

### 低優先度（時間があれば）
7. 📝 **シナリオ実行の抽象化** - アーキテクチャ改善
8. 📝 **エラーハンドリングの統一** - 保守性向上
9. 📝 **テスト容易性の向上** - 長期的品質向上
10. 📝 **ファイル構造の改善** - 大規模リファクタリング

---

## まとめ：リファクタリングの効果

### Before（現在）
- グローバル変数多数
- 長い関数（100行超）
- マジックナンバー散在
- 型情報不足
- テストが困難

### After（リファクタリング後）
- 設定の一元管理
- 単一責任の小さな関数
- 意味のある定数とメソッド
- 完全な型ヒント
- テスト可能な設計

### 期待される改善
- **可読性**: 50%向上
- **保守性**: 70%向上
- **バグ検出**: IDEサポートで早期発見
- **開発速度**: 初期は-20%、慣れれば+30%

---
---

# GUI設定システム開発計画書

## 目的
統合最適化（`cs_optim_unified.py`）のパラメータをGUIで直感的に設定し、グローバル変数や保存先を簡単に変更できるシステムを構築する。

## 既存GUIの状況

### 現在の実装
- **ファイル**: `src/config/config_gui.py`（Streamlitベース）
- **対応**: 平常時・故障時・確率的最適化の基本設定
- **機能**:
  - 基本設定（保存先、シミュレーション時間）
  - 最適化設定（バッチサイズ、トライアル数、収束判定）
  - 故障シナリオ設定（故障確率、故障率、故障時間範囲）
  - JSON保存・読み込み

### 不足している機能
1. ✗ 統合最適化用の故障重み（P値）設定
2. ✗ Worker割り当て設定（outer_parallel）
3. ✗ リアルタイム設定プレビュー
4. ✗ 保存先ディレクトリの自動生成機能
5. ✗ 最適化モード選択（P=0, 0<P<1, P=1）
6. ✗ 設定テンプレート機能
7. ✗ 実行時の設定検証

---

## GUI設計方針

### A. 技術スタック
- **フレームワーク**: Streamlit（既存と統一）
- **設定管理**: dataclass + JSON（既存方式を継承）
- **検証**: Pydantic（型安全性と検証強化）

### B. ユーザー体験
1. **直感的なUI**: スライダー、プルダウン、トグルで視覚的に操作
2. **リアルタイムフィードバック**: 設定変更時に影響を即座に表示
3. **プリセット機能**: よく使う設定を保存・呼び出し
4. **安全性**: 不正な値を入力できない設計

---

## 実装計画

### Phase 1: 統合最適化用の設定クラス拡張

#### 1.1 `UnifiedOptimizationConfig`の作成

**ファイル**: `src/config/unified_optimization_config.py`

```python
"""統合最適化用の設定クラス"""
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Literal
import json


@dataclass
class UnifiedOptimizationConfig:
    """統合最適化の設定（平常時+故障時）"""

    # === 基本設定 ===
    save_dir_base: str = "/srv/samba/share/output"
    experiment_name: str = "unified"  # 実験名（ディレクトリ名に使用）
    t_hour: int = 26

    # === 故障重み設定 ===
    failure_weight: float = 0.5  # P値（0.0〜1.0）
    optimization_mode: Literal["normal", "failure", "unified"] = "unified"

    # === 並列処理設定 ===
    batch_size: int = 8
    outer_parallel: int = 8  # 同時処理するトライアル数
    workers_per_trial: int = 9  # 平常1 + 故障8

    # === 最適化設定 ===
    total_trials: int = 1000
    timeout: int = 86400
    convergence_patience: int = 100
    convergence_threshold: float = 0.001

    # === 故障シナリオ設定 ===
    failure_flag: bool = True
    failure_time: List[int] = field(default_factory=lambda: list(range(27)))

    # === Optuna設定 ===
    n_startup_trials: int = 50  # ランダム探索期間

    @property
    def save_dir(self) -> Path:
        """実際の保存ディレクトリパスを生成"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        p_value = int(self.failure_weight * 100)
        dir_name = f"{timestamp}_{self.experiment_name}_P{p_value:02d}"
        return Path(self.save_dir_base) / dir_name

    @property
    def normal_weight(self) -> float:
        """平常時の重み (1-P)"""
        return 1.0 - self.failure_weight

    @property
    def db_path(self) -> Path:
        """Optunaデータベースのパス"""
        return self.save_dir / 'optuna_study_unified.db'

    def get_objective_formula(self) -> str:
        """目的関数の数式を文字列で返す"""
        return (f"F = {self.normal_weight:.2f} × 平常時コスト + "
                f"{self.failure_weight:.2f} × 故障時コスト")

    def validate(self) -> List[str]:
        """設定の妥当性を検証

        Returns:
            エラーメッセージのリスト（空なら正常）
        """
        errors = []

        if not 0.0 <= self.failure_weight <= 1.0:
            errors.append("failure_weightは0.0〜1.0の範囲で指定してください")

        if self.batch_size < 1 or self.batch_size > 32:
            errors.append("batch_sizeは1〜32の範囲で指定してください")

        if self.outer_parallel < 1 or self.outer_parallel > 16:
            errors.append("outer_parallelは1〜16の範囲で指定してください")

        if self.total_trials < self.convergence_patience:
            errors.append(f"total_trials({self.total_trials})は"
                        f"convergence_patience({self.convergence_patience})以上にしてください")

        if self.t_hour < 1 or self.t_hour > 48:
            errors.append("t_hourは1〜48の範囲で指定してください")

        return errors

    def get_total_workers(self) -> int:
        """必要な総Worker数を計算"""
        return self.outer_parallel * self.workers_per_trial

    def get_estimated_time(self, time_per_trial: float = 5.0) -> dict:
        """推定実行時間を計算

        Args:
            time_per_trial: 1トライアルあたりの実行時間（分）

        Returns:
            推定時間の辞書（分、時間、日）
        """
        total_minutes = (self.total_trials / self.outer_parallel) * time_per_trial
        return {
            'minutes': total_minutes,
            'hours': total_minutes / 60,
            'days': total_minutes / 60 / 24
        }

    @classmethod
    def from_json(cls, path: Path) -> 'UnifiedOptimizationConfig':
        """JSONファイルから設定を読み込み"""
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def to_json(self, path: Path) -> None:
        """JSONファイルに設定を保存"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def create_preset(cls, preset_name: str) -> 'UnifiedOptimizationConfig':
        """プリセット設定を作成

        Args:
            preset_name: "quick_test", "normal_only", "failure_only",
                        "balanced", "robust", "production"
        """
        presets = {
            "quick_test": cls(
                experiment_name="quick_test",
                failure_weight=0.5,
                total_trials=10,
                convergence_patience=5,
                outer_parallel=2
            ),
            "normal_only": cls(
                experiment_name="normal_only",
                failure_weight=0.0,
                optimization_mode="normal",
                workers_per_trial=1
            ),
            "failure_only": cls(
                experiment_name="failure_only",
                failure_weight=1.0,
                optimization_mode="failure"
            ),
            "balanced": cls(
                experiment_name="balanced",
                failure_weight=0.5,
                total_trials=1000
            ),
            "robust": cls(
                experiment_name="robust",
                failure_weight=0.8,
                total_trials=1500,
                convergence_patience=150
            ),
            "production": cls(
                experiment_name="production",
                failure_weight=0.5,
                total_trials=3000,
                timeout=86400 * 2,  # 48時間
                convergence_patience=200
            )
        }
        return presets.get(preset_name, cls())
```

---

### Phase 2: GUI実装

#### 2.1 統合最適化GUI

**ファイル**: `src/config/unified_config_gui.py`

```python
"""統合最適化用のStreamlit GUI"""
import streamlit as st
from pathlib import Path
import json
from unified_optimization_config import UnifiedOptimizationConfig


def main():
    st.set_page_config(
        page_title="統合最適化設定",
        page_icon="🔥",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # ===== サイドバー: プリセット選択 =====
    with st.sidebar:
        st.header("🎯 プリセット設定")

        preset_options = {
            "カスタム": None,
            "クイックテスト (10試行)": "quick_test",
            "平常時のみ (P=0)": "normal_only",
            "故障時のみ (P=1)": "failure_only",
            "バランス型 (P=0.5)": "balanced",
            "堅牢性重視 (P=0.8)": "robust",
            "本番環境 (3000試行)": "production"
        }

        selected_preset = st.selectbox(
            "プリセットを選択",
            options=list(preset_options.keys()),
            help="よく使う設定をすぐに読み込めます"
        )

        # プリセット読み込み
        if selected_preset != "カスタム" and preset_options[selected_preset]:
            if 'config' not in st.session_state or st.button("🔄 プリセットを適用"):
                st.session_state.config = UnifiedOptimizationConfig.create_preset(
                    preset_options[selected_preset]
                )
                st.success(f"✅ {selected_preset}を読み込みました")

        # JSONから読み込み
        st.divider()
        st.subheader("📂 設定ファイル")
        uploaded_file = st.file_uploader("JSONから読み込み", type=['json'])
        if uploaded_file:
            try:
                data = json.load(uploaded_file)
                st.session_state.config = UnifiedOptimizationConfig(**data)
                st.success("✅ 設定を読み込みました")
            except Exception as e:
                st.error(f"❌ エラー: {e}")

    # 初期設定
    if 'config' not in st.session_state:
        st.session_state.config = UnifiedOptimizationConfig()

    config = st.session_state.config

    # ===== メインコンテンツ =====
    st.title("🔥 統合最適化設定 GUI")
    st.markdown("""
    平常時と故障時を統合した最適化の設定を行います。
    **目的関数**: F = (1-P) × 平常時コスト + P × 故障時コスト
    """)

    # ===== タブ構成 =====
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🎯 最適化モード",
        "📁 基本設定",
        "⚡ 並列処理",
        "🔧 詳細設定",
        "📊 プレビュー"
    ])

    # ----- Tab 1: 最適化モード -----
    with tab1:
        st.header("最適化モード選択")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("📊 平常時のみ\n(P=0)", use_container_width=True, type="secondary"):
                config.failure_weight = 0.0
                config.optimization_mode = "normal"
                config.workers_per_trial = 1

        with col2:
            if st.button("🔥 故障時のみ\n(P=1)", use_container_width=True, type="secondary"):
                config.failure_weight = 1.0
                config.optimization_mode = "failure"
                config.workers_per_trial = 9

        with col3:
            if st.button("⚖️ 統合最適化\n(0<P<1)", use_container_width=True, type="primary"):
                config.failure_weight = 0.5
                config.optimization_mode = "unified"
                config.workers_per_trial = 9

        st.divider()

        # P値スライダー
        st.subheader("故障重み（P値）の設定")
        config.failure_weight = st.slider(
            "故障重み P",
            min_value=0.0,
            max_value=1.0,
            value=config.failure_weight,
            step=0.05,
            format="%.2f",
            help="0.0=平常時のみ、1.0=故障時のみ、0.5=両方を均等に考慮"
        )

        # 目的関数の表示
        st.info(f"**目的関数**: {config.get_objective_formula()}")

        # 視覚化
        col_viz1, col_viz2 = st.columns(2)
        with col_viz1:
            st.metric("平常時の重み", f"{config.normal_weight:.2f}")
        with col_viz2:
            st.metric("故障時の重み", f"{config.failure_weight:.2f}")

        # 推奨設定の説明
        with st.expander("💡 P値の選び方ガイド"):
            st.markdown("""
            | P値 | 用途 | 説明 |
            |-----|------|------|
            | 0.0 | コスト最小化 | 平常時のコストのみを最小化 |
            | 0.2-0.3 | 軽微な堅牢性 | 故障時も少し考慮 |
            | 0.5 | バランス型 | 平常時と故障時を同等に考慮 |
            | 0.7-0.8 | 堅牢性重視 | 故障時の性能を重視 |
            | 1.0 | ロバスト設計 | 最悪ケースに対して最適化 |
            """)

    # ----- Tab 2: 基本設定 -----
    with tab2:
        st.header("基本設定")

        col_basic1, col_basic2 = st.columns(2)

        with col_basic1:
            config.experiment_name = st.text_input(
                "実験名",
                value=config.experiment_name,
                help="ディレクトリ名に含まれます"
            )

            config.save_dir_base = st.text_input(
                "保存先ベースディレクトリ",
                value=config.save_dir_base,
                help="この下にタイムスタンプ付きディレクトリが作成されます"
            )

            # 実際の保存先プレビュー
            st.info(f"📁 **実際の保存先**: `{config.save_dir}`")

        with col_basic2:
            config.t_hour = st.number_input(
                "シミュレーション時間（時）",
                min_value=1,
                max_value=48,
                value=config.t_hour,
                help="通常は26時間"
            )

            config.total_trials = st.number_input(
                "総トライアル数",
                min_value=1,
                max_value=10000,
                value=config.total_trials,
                help="最適化の総試行回数"
            )

    # ----- Tab 3: 並列処理 -----
    with tab3:
        st.header("並列処理設定")

        col_para1, col_para2 = st.columns(2)

        with col_para1:
            config.outer_parallel = st.slider(
                "同時実行トライアル数 (outer_parallel)",
                min_value=1,
                max_value=16,
                value=config.outer_parallel,
                help="同時に評価するトライアルの数"
            )

            config.batch_size = st.slider(
                "バッチサイズ",
                min_value=1,
                max_value=32,
                value=config.batch_size,
                help="（互換性のため保持、実際はouter_parallelを使用）"
            )

        with col_para2:
            # Worker数の表示
            total_workers = config.get_total_workers()
            st.metric(
                "必要なWorker数",
                total_workers,
                help=f"{config.outer_parallel}トライアル × {config.workers_per_trial}Worker"
            )

            # 推定実行時間
            time_per_trial = st.number_input(
                "1トライアルあたりの時間（分）",
                min_value=1.0,
                max_value=60.0,
                value=5.0,
                step=0.5,
                help="経験的な実行時間を入力"
            )

            estimated = config.get_estimated_time(time_per_trial)
            st.metric(
                "推定実行時間",
                f"{estimated['hours']:.1f} 時間",
                help=f"{estimated['minutes']:.0f}分 ≈ {estimated['days']:.2f}日"
            )

    # ----- Tab 4: 詳細設定 -----
    with tab4:
        st.header("詳細設定")

        col_adv1, col_adv2 = st.columns(2)

        with col_adv1:
            st.subheader("収束判定")
            config.convergence_patience = st.number_input(
                "収束判定回数",
                min_value=10,
                max_value=500,
                value=config.convergence_patience,
                help="連続してこの回数改善が小さい場合に収束と判定"
            )

            config.convergence_threshold = st.number_input(
                "収束閾値",
                min_value=0.0001,
                max_value=0.1,
                value=config.convergence_threshold,
                format="%.4f",
                help="改善率がこの値未満で収束"
            )

            config.timeout = st.number_input(
                "タイムアウト（秒）",
                min_value=3600,
                max_value=86400 * 7,
                value=config.timeout,
                help="最大実行時間"
            )

        with col_adv2:
            st.subheader("Optuna設定")
            config.n_startup_trials = st.number_input(
                "ランダム探索期間",
                min_value=10,
                max_value=200,
                value=config.n_startup_trials,
                help="最初のランダム探索トライアル数"
            )

            st.subheader("故障シナリオ")
            config.failure_flag = st.checkbox(
                "故障シナリオを有効化",
                value=config.failure_flag
            )

            if config.failure_flag:
                failure_time_range = st.slider(
                    "故障発生時間範囲（時）",
                    min_value=0,
                    max_value=config.t_hour,
                    value=(0, config.t_hour),
                    help="この範囲で故障が発生する可能性がある"
                )
                config.failure_time = list(range(
                    failure_time_range[0],
                    failure_time_range[1] + 1
                ))

    # ----- Tab 5: プレビュー -----
    with tab5:
        st.header("設定プレビュー")

        # 検証
        errors = config.validate()
        if errors:
            st.error("❌ 設定エラー:")
            for error in errors:
                st.write(f"- {error}")
        else:
            st.success("✅ 設定は正常です")

        # サマリー表示
        col_sum1, col_sum2, col_sum3 = st.columns(3)

        with col_sum1:
            st.subheader("最適化設定")
            st.write(f"- モード: {config.optimization_mode}")
            st.write(f"- 故障重み: {config.failure_weight:.2f}")
            st.write(f"- トライアル数: {config.total_trials}")
            st.write(f"- 収束判定: {config.convergence_patience}回")

        with col_sum2:
            st.subheader("並列処理")
            st.write(f"- 同時トライアル: {config.outer_parallel}")
            st.write(f"- Worker/トライアル: {config.workers_per_trial}")
            st.write(f"- 総Worker数: {config.get_total_workers()}")

        with col_sum3:
            st.subheader("実行環境")
            st.write(f"- 保存先: `{config.experiment_name}`")
            st.write(f"- シミュレーション時間: {config.t_hour}時間")
            st.write(f"- タイムアウト: {config.timeout/3600:.1f}時間")

        # JSON表示
        with st.expander("📄 JSON設定（デバッグ用）"):
            st.json(asdict(config))

    # ===== 保存ボタン =====
    st.divider()
    col_save1, col_save2, col_save3 = st.columns([2, 1, 1])

    with col_save1:
        config_filename = st.text_input(
            "設定ファイル名",
            value="unified_config.json",
            help="保存する設定ファイル名"
        )

    with col_save2:
        if st.button("💾 設定を保存", type="primary", use_container_width=True):
            try:
                config.to_json(Path(config_filename))
                st.success(f"✅ `{config_filename}`に保存しました")
            except Exception as e:
                st.error(f"❌ 保存エラー: {e}")

    with col_save3:
        if st.button("🚀 最適化を実行", type="primary", use_container_width=True):
            st.info("🚧 実装予定: 最適化スクリプトを直接起動")
            # TODO: subprocess で cs_optim_unified.py を実行

    # ===== 使用方法 =====
    with st.expander("📖 使用方法"):
        st.markdown(f"""
        ### GUI起動方法
        ```bash
        cd {Path.cwd()}
        source .venv/bin/activate
        streamlit run src/config/unified_config_gui.py
        ```

        ### 設定ファイルの使用方法
        ```python
        from src.config.unified_optimization_config import UnifiedOptimizationConfig

        # 設定読み込み
        config = UnifiedOptimizationConfig.from_json(Path("unified_config.json"))

        # グローバル変数として使用
        SAVE_DIR = str(config.save_dir)
        T_HOUR = config.t_hour
        FAILURE_WEIGHT = config.failure_weight
        OUTER_PARALLEL = config.outer_parallel
        ```

        ### プリセット一覧
        - **クイックテスト**: 10トライアル、動作確認用
        - **平常時のみ**: P=0、Worker1個のみ
        - **故障時のみ**: P=1、故障シナリオのみ評価
        - **バランス型**: P=0.5、1000トライアル
        - **堅牢性重視**: P=0.8、故障時を重視
        - **本番環境**: 3000トライアル、48時間タイムアウト
        """)


if __name__ == "__main__":
    main()
```

---

### Phase 3: 最適化スクリプトとの統合

#### 3.1 統合最適化スクリプトの修正

**ファイル**: `cs_optim_unified.py`（新規作成予定）

```python
"""統合最適化メインスクリプト（GUI設定対応版）"""
import sys
from pathlib import Path

# 設定読み込み
from src.config.unified_optimization_config import UnifiedOptimizationConfig

def load_config_from_args() -> UnifiedOptimizationConfig:
    """コマンドライン引数またはデフォルトから設定を読み込み"""
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
        if config_path.exists():
            print(f"📂 設定ファイルを読み込み: {config_path}")
            return UnifiedOptimizationConfig.from_json(config_path)
        else:
            print(f"⚠️ 設定ファイルが見つかりません: {config_path}")

    # デフォルト設定
    print("📋 デフォルト設定を使用")
    return UnifiedOptimizationConfig()

if __name__ == "__main__":
    # 設定読み込み
    config = load_config_from_args()

    # 設定検証
    errors = config.validate()
    if errors:
        print("❌ 設定エラー:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    # グローバル変数に設定を適用
    SAVE_DIR = str(config.save_dir)
    T_HOUR = config.t_hour
    FAILURE_WEIGHT = config.failure_weight
    FAILURE_FLAG = config.failure_flag
    FAILURE_TIME = config.failure_time
    BATCH_SIZE = config.batch_size
    OUTER_PARALLEL = config.outer_parallel
    TOTAL_TRIALS = config.total_trials
    TIMEOUT = config.timeout
    CONVERGENCE_PATIENCE = config.convergence_patience
    CONVERGENCE_THRESHOLD = config.convergence_threshold

    # ディレクトリ作成
    config.save_dir.mkdir(parents=True, exist_ok=True)

    # 設定を保存
    config.to_json(config.save_dir / "config_used.json")

    print(f"📂 結果保存先: {SAVE_DIR}")
    print(f"⚙️ 故障率P: {FAILURE_WEIGHT}")
    print(f"📊 目的関数: {config.get_objective_formula()}")

    # 既存の最適化処理を実行
    # ... (既存のコードをここに配置)
```

#### 3.2 実行方法

```bash
# GUI設定なし（デフォルト）
python cs_optim_unified.py

# GUI設定を使用
python cs_optim_unified.py unified_config.json
```

---

## 追加機能案

### A. 実行中モニタリング GUI

**ファイル**: `src/config/monitor_gui.py`

```python
"""最適化実行のリアルタイムモニタリング"""
import streamlit as st
import optuna
import pandas as pd
import plotly.express as px
from pathlib import Path

def main():
    st.title("📊 最適化実行モニター")

    # データベース選択
    db_path = st.text_input("Optunaデータベースパス", value="optuna_study_unified.db")
    study_name = st.text_input("Study名", value="cs_optimization_unified")

    if Path(db_path).exists():
        try:
            study = optuna.load_study(
                study_name=study_name,
                storage=f"sqlite:///{db_path}"
            )

            # 基本統計
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("トライアル数", len(study.trials))
            with col2:
                st.metric("最適値", f"{study.best_value:.2f}")
            with col3:
                st.metric("ベストトライアル", study.best_trial.number)

            # 履歴グラフ
            df = study.trials_dataframe()
            fig = px.line(df, x='number', y='value', title='最適化履歴')
            st.plotly_chart(fig)

            # ベストトライアル詳細
            st.subheader("🏆 ベストトライアル")
            best = study.best_trial
            st.json(best.params)
            st.json(best.user_attrs)

        except Exception as e:
            st.error(f"❌ エラー: {e}")
    else:
        st.warning("データベースファイルが見つかりません")

if __name__ == "__main__":
    main()
```

### B. 設定比較ツール

```python
"""複数の設定ファイルを比較"""
def compare_configs(config1: UnifiedOptimizationConfig,
                   config2: UnifiedOptimizationConfig) -> pd.DataFrame:
    """2つの設定を比較してDataFrameで返す"""
    diff = []
    for key in asdict(config1).keys():
        val1 = getattr(config1, key)
        val2 = getattr(config2, key)
        if val1 != val2:
            diff.append({
                'パラメータ': key,
                '設定1': val1,
                '設定2': val2,
                '差分': '異なる' if val1 != val2 else '同じ'
            })
    return pd.DataFrame(diff)
```

---

## ディレクトリ構造

```
emates/
├── cs_optim_unified.py              # 統合最適化スクリプト（GUI対応）
├── src/
│   └── config/
│       ├── __init__.py
│       ├── optimization_config.py   # 既存（平常時・故障時用）
│       ├── config_gui.py            # 既存GUI
│       ├── unified_optimization_config.py  # 新規：統合設定クラス
│       ├── unified_config_gui.py    # 新規：統合GUI
│       └── monitor_gui.py           # 新規：モニタリングGUI
└── configs/                         # 設定ファイル保存先（新規）
    ├── presets/
    │   ├── quick_test.json
    │   ├── balanced.json
    │   └── production.json
    └── custom/
        └── my_config.json
```

---

## 実装手順

### Step 1: 設定クラス作成（1-2時間）
- [ ] `unified_optimization_config.py`を作成
- [ ] プリセット機能を実装
- [ ] 検証ロジックを実装

### Step 2: GUI実装（3-4時間）
- [ ] `unified_config_gui.py`の基本構造
- [ ] 各タブの実装
- [ ] プリセット機能の統合

### Step 3: スクリプト統合（1-2時間）
- [ ] `cs_optim_unified.py`で設定読み込み
- [ ] グローバル変数への適用
- [ ] 動作確認

### Step 4: テスト（1時間）
- [ ] 各プリセットで動作確認
- [ ] 設定の保存・読み込み確認
- [ ] エラーハンドリング確認

### Step 5: ドキュメント作成（1時間）
- [ ] README更新
- [ ] 使用方法の説明
- [ ] トラブルシューティング

**総見積もり時間**: 7-10時間

---

## 使用例

### ケース1: GUIで設定して実行

```bash
# 1. GUI起動
streamlit run src/config/unified_config_gui.py

# 2. GUIで設定を調整
#    - プリセット「バランス型」を選択
#    - P値を0.6に変更
#    - 「設定を保存」ボタンクリック → unified_config.json

# 3. 最適化実行
python cs_optim_unified.py unified_config.json
```

### ケース2: プリセットを直接使用

```python
from src.config.unified_optimization_config import UnifiedOptimizationConfig

# プリセット読み込み
config = UnifiedOptimizationConfig.create_preset("robust")

# 一部カスタマイズ
config.experiment_name = "my_robust_test"
config.total_trials = 500

# 保存
config.to_json(Path("my_config.json"))
```

### ケース3: モニタリング

```bash
# 最適化実行中に別ターミナルで
streamlit run src/config/monitor_gui.py

# リアルタイムで進捗を確認
```

---

## メリット

### 開発者視点
- ✅ グローバル変数の一元管理
- ✅ 設定の再現性確保
- ✅ 実験管理が容易

### ユーザー視点
- ✅ 直感的な設定変更
- ✅ プリセットで素早く開始
- ✅ 設定ミスの防止

### チーム視点
- ✅ 設定の共有が簡単
- ✅ 標準化された実験手順
- ✅ トラブルシューティングが容易

---

## 今後の拡張案

1. **実行管理機能**: GUI から直接最適化を起動・停止
2. **結果可視化**: 最適化完了後の結果をGUIで表示
3. **設定レコメンド**: 過去の実行結果から推奨設定を提案
4. **クラウド連携**: 設定をクラウドに保存・共有
5. **通知機能**: 最適化完了時にメール/Slack通知
