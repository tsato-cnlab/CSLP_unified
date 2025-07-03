import sys
import argparse
import logging
import json
import pandas as pd
import numpy as np
import h5py
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import re
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm

from src.util.log_manager import setup_logging
from src.simulation.run_emates import run_parallel_emates_simulations
from src.util.path_manager import get_paths

class EMATESPipeline:
    def __init__(self, parallel_workers: int = 4, debug: bool = False):
        self.parallel_workers = parallel_workers
        self.debug = debug
        self.logger = self._setup_logging()
        self.scenario_data = {}
        self.optimization_results = {}  # 最適化結果保存用


    # ===== 単年度逐次配置計画 =====
    def run_yearly_optimization(self, scenario_id: int, year: int, worker_ids: List[int] = [1]) -> Dict:
        """単年度の最適化実行"""
        self.logger.info(f"シナリオ{scenario_id} - {year}年目の最適化開始")
        
        # 1. eMATES実行（現在のCS設定で）
        yearly_data = self.collect_scenario_data(scenario_id, year, worker_ids)
        
        # 2. データ評価
        performance = self._evaluate_performance(yearly_data)
        
        # 3. MILP問題定式化・最適化
        optimal_config = self._optimize_cs_configuration(yearly_data, performance)
        
        # 4. 次年度設定更新
        self._update_cs_configuration(scenario_id, year + 1, optimal_config)
        
        # 結果保存
        result = {
            "scenario_id": scenario_id,
            "year": year,
            "performance": performance,
            "optimal_config": optimal_config,
            "simulation_data": yearly_data
        }
        
        key = f"scenario_{scenario_id}_year_{year}"
        self.optimization_results[key] = result
        
        self.logger.info(f"シナリオ{scenario_id} - {year}年目の最適化完了")
        return result

    # ===== 長期間シナリオ計画 =====
    def run_long_term_scenario_planning(self, scenario_ids: List[int] = [1, 2, 3, 4], 
                                        start_year: int = 0, end_year: int = 10) -> Dict:
        """複数シナリオの長期間計画実行"""
        self.logger.info(f"長期間シナリオ計画開始: シナリオ{scenario_ids}, {start_year}-{end_year}年")
        
        all_results = {}
        
        for scenario_id in scenario_ids:
            self.logger.info(f"シナリオ{scenario_id}の処理開始")
            scenario_results = {}
            
            # 初期CS設定
            self._initialize_cs_configuration(scenario_id)
            
            # 年次ループ
            for year in range(start_year, end_year + 1):
                yearly_result = self.run_yearly_optimization(scenario_id, year)
                scenario_results[f"year_{year}"] = yearly_result
                
                # 進捗表示
                progress = (year - start_year + 1) / (end_year - start_year + 1) * 100
                self.logger.info(f"シナリオ{scenario_id}: {progress:.1f}% 完了")
            
            all_results[f"scenario_{scenario_id}"] = scenario_results
            self.logger.info(f"シナリオ{scenario_id}完了")
        
        self.logger.info("全シナリオの長期間計画完了")
        return all_results

    # ===== コア機能 =====
    def collect_scenario_data(self, scenario_id: int, year: int, worker_ids: List[int]) -> Dict:
        """シナリオ・年度別データ収集"""
        from src.util.scenario import get_adoption_rate
        
        ev_rate = get_adoption_rate(scenario_id, year)
        
        scenario_data = {
            "scenario_id": scenario_id,
            "year": year,
            "metadata": {
                "ev_adoption_rate": ev_rate,
                "collected_at": datetime.now().isoformat()
            },
            "cs_data": {}
        }
        
        for worker_id in worker_ids:
            try:
                paths = get_paths(worker_id)
                result_dir = Path(paths["result"])
                worker_data = self._load_worker_data(worker_id, result_dir)
                scenario_data["cs_data"][f"worker_{worker_id}"] = worker_data
            except Exception as e:
                self.logger.error(f"Worker {worker_id} 処理エラー: {e}")
        
        return scenario_data

    def _evaluate_performance(self, yearly_data: Dict) -> Dict:
        """性能評価"""
        metrics = {
            "profit": 0,
            "waiting_time": 0,
            "loss_count": 0,
            "utilization": 0
        }
        
        for worker_name, data in yearly_data["cs_data"].items():
            # 利潤計算
            revenue = self._calculate_revenue(data)
            initial_cost = self._initial_cost(data)
            operating_cost = self._operating_cost(data['timeseries'])
            profit = revenue - initial_cost - operating_cost
            
            # 待機時間計算
            vehicle_trip = data['vehicle_trip']
            non_zero = vehicle_trip[vehicle_trip['WaitingEntryTime'] != 0]
            if not non_zero.empty:
                waiting_times = non_zero['startChargingTime'].values - non_zero['WaitingEntryTime'].values
                avg_waiting = waiting_times[waiting_times > 0].mean()
            else:
                avg_waiting = 0
            
            # ロス回数
            loss_count = len(data['charging_loss'])
            
            metrics["profit"] += profit
            metrics["waiting_time"] += avg_waiting
            metrics["loss_count"] += loss_count
        
        return metrics

    def _optimize_cs_configuration(self, yearly_data: Dict, performance: Dict) -> Dict:
        """MILP最適化（簡略版）"""
        # 現在の設定を基準に改善案を生成
        current_config = yearly_data["cs_data"]["worker_1"]
        
        # 簡単な最適化ロジック（実際にはMILPソルバーを使用）
        if performance["waiting_time"] > 100:  # 待機時間が長い場合
            # ポート数を増加
            new_ports = [p + 1 for p in current_config["ports"]]
        else:
            # 現状維持
            new_ports = current_config["ports"]
        
        optimal_config = {
            "csids": current_config["csids"],
            "ports": new_ports,
            "cap_kw": current_config["cap_kw"]
        }
        
        return optimal_config

    def _update_cs_configuration(self, scenario_id: int, year: int, config: Dict):
        """CS設定更新（次年度用）"""
        # 実際にはeMATESの設定ファイルを更新
        self.logger.info(f"シナリオ{scenario_id} - {year}年目のCS設定更新")
        # TODO: csList.txtファイルの更新処理

    def _initialize_cs_configuration(self, scenario_id: int):
        """初期CS設定"""
        self.logger.info(f"シナリオ{scenario_id}の初期CS設定")
        # TODO: 初期設定の定義

    # ===== 結果分析・可視化 =====
    def get_optimization_summary(self) -> pd.DataFrame:
        """最適化結果のサマリー取得"""
        summary_data = []
        
        for key, result in self.optimization_results.items():
            summary_data.append({
                "scenario_id": result["scenario_id"],
                "year": result["year"],
                "profit": result["performance"]["profit"],
                "waiting_time": result["performance"]["waiting_time"],
                "loss_count": result["performance"]["loss_count"],
                "total_ports": sum(result["optimal_config"]["ports"])
            })
        
        return pd.DataFrame(summary_data)

    def save_results(self, filepath: str = None):
        """結果保存"""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"optimization_results_{timestamp}.json"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.optimization_results, f, ensure_ascii=False, indent=2, default=str)
        
        self.logger.info(f"最適化結果を保存: {filepath}")
        
    def _setup_logging(self) -> logging.Logger:
        """ロギングのセットアップ"""
        setup_logging(self.debug)
        return logging.getLogger(__name__)
    
if __name__ == "__main__":
    pipeline = EMATESPipeline(parallel_workers=1, debug=True)
    parser = argparse.ArgumentParser(description="eMATES最適化パイプライン")
    
