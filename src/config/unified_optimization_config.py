"""統合最適化用の設定クラス"""
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Literal, Callable
import json


@dataclass
class ObjectiveFunction:
    """目的関数の定義を管理するクラス"""

    name: str = "weighted_sum"
    formula: str = "(1-P) * normal + P * failure"
    description: str = "重み付き和（デフォルト）"

    def calculate(self, normal_cost: float, failure_cost: float, p: float) -> float:
        """目的関数を計算

        Args:
            normal_cost: 平常時コスト
            failure_cost: 故障時コスト
            p: 故障重み（failure_weight）

        Returns:
            統合コスト
        """
        if self.name == "weighted_sum":
            return (1 - p) * normal_cost + p * failure_cost

        elif self.name == "max":
            # 最大値を最小化（保守的）
            return max(normal_cost, failure_cost)

        elif self.name == "weighted_max":
            # 重み付き最大値
            return max((1 - p) * normal_cost, p * failure_cost)

        elif self.name == "geometric_mean":
            # 幾何平均
            if normal_cost <= 0 or failure_cost <= 0:
                return float('inf')
            return (normal_cost ** (1 - p)) * (failure_cost ** p)

        elif self.name == "custom":
            # カスタム式を評価
            try:
                # 安全な評価のため、許可された関数のみ使用
                safe_dict = {
                    'normal': normal_cost,
                    'failure': failure_cost,
                    'P': p,
                    'max': max,
                    'min': min,
                    'abs': abs,
                }
                return eval(self.formula, {"__builtins__": {}}, safe_dict)
            except Exception as e:
                print(f"カスタム式の評価エラー: {e}")
                return float('inf')

        else:
            # デフォルトは重み付き和
            return (1 - p) * normal_cost + p * failure_cost

    def get_formula_display(self, p: float) -> str:
        """目的関数の数式を表示用に整形"""
        if self.name == "weighted_sum":
            return f"F = {1-p:.2f} × 平常時 + {p:.2f} × 故障時"
        elif self.name == "max":
            return "F = max(平常時, 故障時)"
        elif self.name == "weighted_max":
            return f"F = max({1-p:.2f} × 平常時, {p:.2f} × 故障時)"
        elif self.name == "geometric_mean":
            return f"F = 平常時^{1-p:.2f} × 故障時^{p:.2f}"
        elif self.name == "custom":
            return f"F = {self.formula}"
        else:
            return self.formula

    @classmethod
    def get_predefined_functions(cls) -> dict:
        """事前定義された目的関数のリストを取得"""
        return {
            "weighted_sum": cls(
                name="weighted_sum",
                formula="(1-P) * normal + P * failure",
                description="重み付き和（デフォルト）"
            ),
            "max": cls(
                name="max",
                formula="max(normal, failure)",
                description="最大値（最も保守的）"
            ),
            "weighted_max": cls(
                name="weighted_max",
                formula="max((1-P) * normal, P * failure)",
                description="重み付き最大値"
            ),
            "geometric_mean": cls(
                name="geometric_mean",
                formula="normal^(1-P) * failure^P",
                description="幾何平均"
            ),
        }


@dataclass
class UnifiedOptimizationConfig:
    """統合最適化の設定（平常時+故障時）"""

    # === 基本設定 ===
    save_dir_base: str = "/srv/samba/share/output"
    experiment_name: str = "unified"
    t_hour: int = 26

    # === 故障重み設定 ===
    failure_weight: float = 0.5
    optimization_mode: Literal["normal", "failure", "unified"] = "unified"

    # === 目的関数設定 ===
    objective_function: ObjectiveFunction = field(default_factory=lambda: ObjectiveFunction())

    # === 並列処理設定 ===
    batch_size: int = 8
    outer_parallel: int = 8
    workers_per_trial: int = 9

    # === 最適化設定 ===
    total_trials: int = 1000
    timeout: int = 86400
    convergence_patience: int = 100
    convergence_threshold: float = 0.001

    # === 故障シナリオ設定 ===
    failure_flag: bool = True
    failure_time: List[int] = field(default_factory=lambda: list(range(27)))

    # === Optuna設定 ===
    n_startup_trials: int = 50

    # === 初期CS配置設定 ===
    initial_cs_configs: Optional[List[dict]] = None
    # フォーマット例: [{"name": "均等配置", "placements": [[900000, 1], [900002, 1]]}, ...]
    initial_cs_config_file: Optional[str] = None  # CSVファイルパス

    @property
    def save_dir(self) -> Path:
        """実際の保存ディレクトリパスを生成"""
        # timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        # p_value = int(self.failure_weight * 100)
        # dir_name = f"{timestamp}_{self.experiment_name}_P{p_value:02d}"
        p_value = int(self.failure_weight * 100)
        dir_name = f"{self.experiment_name}_P{p_value:02d}"
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
        return self.objective_function.get_formula_display(self.failure_weight)

    def calculate_objective(self, normal_cost: float, failure_cost: float) -> float:
        """目的関数を計算"""
        return self.objective_function.calculate(
            normal_cost, failure_cost, self.failure_weight
        )

    def validate(self) -> List[str]:
        """設定の妥当性を検証"""
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

        # カスタム目的関数のテスト
        if self.objective_function.name == "custom":
            try:
                test_result = self.objective_function.calculate(100.0, 150.0, 0.5)
                if test_result == float('inf'):
                    errors.append("カスタム目的関数の評価に失敗しました")
            except Exception as e:
                errors.append(f"カスタム目的関数のエラー: {e}")

        return errors

    def get_total_workers(self) -> int:
        """必要な総Worker数を計算"""
        return self.outer_parallel * self.workers_per_trial

    def get_estimated_time(self, time_per_trial: float = 5.0) -> dict:
        """推定実行時間を計算"""
        total_minutes = (self.total_trials / self.outer_parallel) * time_per_trial
        return {
            'minutes': total_minutes,
            'hours': total_minutes / 60,
            'days': total_minutes / 60 / 24
        }

    @classmethod
    def from_json(cls, path: Path) -> 'UnifiedOptimizationConfig':
        """JSONファイルから設定を読み込み"""
        with open(path, encoding='utf-8') as f:
            data = json.load(f)

        # ObjectiveFunctionの復元
        if 'objective_function' in data:
            obj_func_data = data['objective_function']
            data['objective_function'] = ObjectiveFunction(**obj_func_data)

        # 初期CS配置をCSVから読み込み（ファイル指定がある場合）
        if 'initial_cs_config_file' in data and data['initial_cs_config_file']:
            csv_path = Path(data['initial_cs_config_file'])
            if csv_path.exists():
                data['initial_cs_configs'] = cls._load_initial_cs_from_csv(csv_path)
            else:
                print(f"⚠️ 初期CS配置ファイルが見つかりません: {csv_path}")

        return cls(**data)

    @staticmethod
    def _load_initial_cs_from_csv(csv_path: Path) -> List[dict]:
        """CSVファイルから初期CS配置を読み込み

        CSVフォーマット:
        config_name,csid,capacity_kw,ports
        均等配置,900000,100,1
        均等配置,900002,100,1
        集中配置,900000,150,2
        """
        import csv
        configs_dict = {}

        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    config_name = row['config_name']
                    csid = int(row['csid'])
                    capacity_kw = int(row['capacity_kw'])
                    ports = int(row['ports'])
                    if config_name not in configs_dict:
                        configs_dict[config_name] = {
                            'name': config_name,
                            'placements': []
                        }

                    configs_dict[config_name]['placements'].append([csid, ports, capacity_kw])

            return list(configs_dict.values())
        except Exception as e:
            print(f"❌ 初期CS配置CSV読み込みエラー: {e}")
            return []

    def to_json(self, path: Path) -> None:
        """JSONファイルに設定を保存"""
        data = asdict(self)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def create_preset(cls, preset_name: str) -> 'UnifiedOptimizationConfig':
        """プリセット設定を作成"""
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
                timeout=86400 * 2,
                convergence_patience=200
            )
        }
        return presets.get(preset_name, cls())
