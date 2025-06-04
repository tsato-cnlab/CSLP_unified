#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
eMATESシミュレーション統合パイプライン
実行 → データ収集 → 配置評価を一括処理
"""

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

# プロジェクトルートをPythonパスに追加
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.util.log_manager import setup_logging
from src.simulation.run_emates import run_parallel_emates_simulations
from src.util.path_manager import get_paths

class EMATESPipeline:
    """eMATESシミュレーションの統合パイプライン"""
    
    def __init__(self, parallel_workers: int = 4, debug: bool = False):
        self.parallel_workers = parallel_workers
        self.debug = debug
        self.logger = self._setup_logging()
        
    def _setup_logging(self):
        """ログ設定"""
        setup_logging(self.debug)
        return logging.getLogger(__name__)
    
    def load_cs_configurations(self, config_path: str) -> List[Dict]:
        """CS配置設定を読み込み"""
        try:
            with open(config_path, 'r') as f:
                solutions = json.load(f)
            self.logger.info(f"CS配置設定を読み込み: {len(solutions)}個の設定")
            return solutions
        except (ValueError, FileNotFoundError) as e:
            self.logger.error(f"設定読み込みエラー: {e}")
            raise
    
    def run_simulations(self, solutions: List[Dict]) -> int:
        """シミュレーション実行"""
        self.logger.info(f"シミュレーション開始: {len(solutions)}個の設定")
        
        # 各設定を順次実行（並列化も可能）
        for i, solution in enumerate(solutions):
            self.logger.info(f"設定 {i+1}/{len(solutions)} を実行中...")
            result = run_parallel_emates_simulations(solution, self.parallel_workers)
            if result != 0:
                self.logger.error(f"設定 {i+1} の実行に失敗")
                return result
        
        self.logger.info("全シミュレーション完了")
        return 0
    
    def collect_and_evaluate_results(self, max_workers: int = 100) -> Dict:
        """結果収集と配置評価を同時実行"""
        self.logger.info("結果収集と評価を開始")
        
        evaluation_results = {}
        
        for worker_id in range(1, max_workers + 1):
            try:
                paths = get_paths(worker_id)
                result_dir = Path(paths["res"])
                
                if not result_dir.exists():
                    self.logger.info(f"Worker {worker_id} が見つからないため処理終了")
                    break
                
                # データ収集
                worker_data = self._load_worker_data(worker_id, result_dir)
                
                # 配置評価
                evaluation = self._evaluate_cs_allocation(worker_data)
                evaluation_results[f"worker_{worker_id}"] = {
                    'data': worker_data,
                    'evaluation': evaluation
                }
                
                self.logger.info(f"Worker {worker_id} 処理完了")
                
            except Exception as e:
                self.logger.error(f"Worker {worker_id} 処理エラー: {e}")
                continue
        
        self.logger.info(f"総計 {len(evaluation_results)} ワーカーの結果を処理")
        return evaluation_results
    
    def _load_worker_data(self, worker_id: int, result_dir: Path) -> Dict:
        """単一ワーカーのデータ読み込み"""
        emates_dir = result_dir / "emates"
        
        # 時系列データ（Tファイル）
        t_data = self._load_T_files(emates_dir)
        
        # 充電ロスデータ
        charging_loss = self._load_charging_loss(result_dir)
        
        # 走行データ
        vehicle_trip = self._load_vehicle_trip(result_dir)
        
        return {
            "worker_id": worker_id,
            "result_dir": result_dir,
            "timeseries": t_data,
            "charging_loss": charging_loss,
            "vehicle_trip": vehicle_trip
        }
    
    def _load_T_files(self, emates_dir: Path) -> pd.DataFrame:
        """Tファイル（時系列データ）の読み込み"""
        try:
            t_files = sorted(
                emates_dir.glob("T*.csv"),
                key=lambda x: int(re.search(r"T(\d{6})", x.stem).group(1))
            )
            
            if not t_files:
                return pd.DataFrame()
            
            t_dfs = []
            for f in t_files:
                elapsed = int(re.search(r"T(\d{6})", f.stem).group(1))
                df = pd.read_csv(f)
                df['ElapsedTime'] = elapsed
                t_dfs.append(df)
            
            return pd.concat(t_dfs, ignore_index=True)
        except Exception as e:
            self.logger.warning(f"Tファイル読み込みエラー: {e}")
            return pd.DataFrame()
    
    def _load_charging_loss(self, result_dir: Path) -> pd.DataFrame:
        """充電ロスデータの読み込み"""
        try:
            charging_loss_path = result_dir / "chargingLoss.txt"
            if not charging_loss_path.exists():
                return pd.DataFrame()
            
            return pd.read_csv(
                charging_loss_path, sep=r'\s+',
                names=['Time', 'EVID', 'CSID', 'WaitingNum', 'NumPorts', 'SOC']
            )
        except Exception as e:
            self.logger.warning(f"充電ロスデータ読み込みエラー: {e}")
            return pd.DataFrame()
    
    def _load_vehicle_trip(self, result_dir: Path) -> pd.DataFrame:
        """走行データの読み込み"""
        try:
            vehicle_trip_path = result_dir / "vehicleTrip.txt"
            if not vehicle_trip_path.exists():
                return pd.DataFrame()
            
            return pd.read_csv(
                vehicle_trip_path, sep=r'\s+',
                names=['StartTime', 'EndTime', 'CSID', 'InitialSOC']
            )
        except Exception as e:
            self.logger.warning(f"走行データ読み込みエラー: {e}")
            return pd.DataFrame()
    
    def _evaluate_cs_allocation(self, worker_data: Dict) -> Dict:
        """CS配置の評価"""
        timeseries = worker_data['timeseries']
        charging_loss = worker_data['charging_loss']
        vehicle_trip = worker_data['vehicle_trip']
        
        if timeseries.empty:
            return {'error': 'No timeseries data'}
        
        # CS配置情報を抽出
        if 'Csid' in timeseries.columns:
            unique_csids = timeseries['Csid'].unique()
            cs_locations = sorted(set([int(csid // 100) for csid in unique_csids if pd.notna(csid)]))
        else:
            cs_locations = []
        
        # 基本評価指標を計算
        evaluation = {
            'cs_locations': cs_locations,
            'total_cs_count': len(unique_csids) if 'Csid' in timeseries.columns else 0,
            'simulation_duration': timeseries['ElapsedTime'].max() if 'ElapsedTime' in timeseries.columns else 0,
        }
        
        # 利用率計算
        if 'waitingLine' in timeseries.columns and 'Cap_kW' in timeseries.columns:
            # 時系列での平均待ち時間
            evaluation['avg_waiting'] = timeseries['waitingLine'].mean()
            evaluation['max_waiting'] = timeseries['waitingLine'].max()
            
            # 利用率計算（簡易版）
            if 'Cap_kW' in timeseries.columns:
                total_capacity = timeseries.groupby('ElapsedTime')['Cap_kW'].sum().mean()
                evaluation['avg_utilization'] = min(1.0, timeseries['waitingLine'].mean() / max(1, total_capacity))
        
        # 充電機会損失計算
        if not charging_loss.empty:
            evaluation['total_charging_loss'] = len(charging_loss)
            evaluation['avg_soc_at_loss'] = charging_loss['SOC'].mean() if 'SOC' in charging_loss.columns else 0
        else:
            evaluation['total_charging_loss'] = 0
            evaluation['avg_soc_at_loss'] = 0
        
        # 走行効率計算
        if not vehicle_trip.empty and 'InitialSOC' in vehicle_trip.columns:
            evaluation['avg_initial_soc'] = vehicle_trip['InitialSOC'].mean()
            evaluation['total_trips'] = len(vehicle_trip)
        else:
            evaluation['avg_initial_soc'] = 0
            evaluation['total_trips'] = 0
        
        # 総合評価スコア（重み付け）
        score = 0
        if evaluation['total_cs_count'] > 0:
            # 利用率が高く、待ち時間が少なく、充電損失が少ないほど高得点
            utilization_score = evaluation.get('avg_utilization', 0) * 100
            waiting_penalty = min(50, evaluation.get('avg_waiting', 0) * 10)  # 待ち時間ペナルティ
            loss_penalty = min(30, evaluation.get('total_charging_loss', 0) / 10)  # 損失ペナルティ
            
            score = max(0, utilization_score - waiting_penalty - loss_penalty)
        
        evaluation['overall_score'] = score
        
        return evaluation
    
    def save_results(self, results: Dict, output_file: str = 'emates_results') -> None:
        """結果をemates/results/に保存（CSV形式）"""
        self.logger.info(f"結果を保存中...")
        
        # emates直下のresultsディレクトリに固定
        emates_dir = Path(__file__).parent  # ematesディレクトリ
        output_path = emates_dir / 'results' / Path(output_file).stem
        output_path.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"保存先: {output_path}")
        
        # 評価結果サマリー
        summary_data = []
        
        for worker_name, worker_result in results.items():
            data = worker_result['data']
            evaluation = worker_result['evaluation']
            
            # 個別データ保存（CSV形式）
            worker_dir = output_path / worker_name
            worker_dir.mkdir(exist_ok=True)
            
            if not data['timeseries'].empty:
                data['timeseries'].to_csv(
                    worker_dir / 'timeseries.csv',
                    index=False
                )
            
            if not data['charging_loss'].empty:
                data['charging_loss'].to_csv(
                    worker_dir / 'charging_loss.csv',
                    index=False
                )
            
            if not data['vehicle_trip'].empty:
                data['vehicle_trip'].to_csv(
                    worker_dir / 'vehicle_trip.csv',
                    index=False
                )
            
            # 評価結果をサマリーに追加
            summary_row = {
                'worker_id': data['worker_id'],
                'cs_locations': str(evaluation.get('cs_locations', [])),
                'total_cs_count': evaluation.get('total_cs_count', 0),
                'avg_utilization': evaluation.get('avg_utilization', 0),
                'avg_waiting': evaluation.get('avg_waiting', 0),
                'total_charging_loss': evaluation.get('total_charging_loss', 0),
                'overall_score': evaluation.get('overall_score', 0)
            }
            summary_data.append(summary_row)
        
        # サマリーテーブル保存（CSVのみ）
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_csv(
                output_path / 'evaluation_summary.csv',
                index=False
            )
            
            # 評価結果の表示
            self._display_evaluation_summary(summary_df)
        
        # メタデータをJSONで保存
        metadata = {
            'created_at': datetime.now().isoformat(),
            'total_workers': len(results),
            'pipeline_version': '1.0',
            'output_format': 'csv',
            'save_location': str(output_path)
        }
        
        import json
        with open(output_path / 'metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)
        
        self.logger.info(f"結果保存完了: {output_path}")
    
    def _display_evaluation_summary(self, summary_df: pd.DataFrame) -> None:
        """評価結果サマリーの表示"""
        print("\n" + "="*60)
        print("CS配置評価結果サマリー")
        print("="*60)
        
        # 上位5配置
        top_configs = summary_df.nlargest(5, 'overall_score')
        print("\n【総合スコア上位配置】")
        for _, row in top_configs.iterrows():
            print(f"Worker {row['worker_id']:2d}: "
                  f"スコア {row['overall_score']:6.1f} | "
                  f"CS数 {row['total_cs_count']:2d} | "
                  f"利用率 {row['avg_utilization']:5.1%} | "
                  f"損失 {row['total_charging_loss']:4.0f}")
        
        # 統計情報
        print(f"\n【全体統計】")
        print(f"総設定数: {len(summary_df)}")
        print(f"平均スコア: {summary_df['overall_score'].mean():.1f}")
        print(f"平均CS数: {summary_df['total_cs_count'].mean():.1f}")
        print(f"平均利用率: {summary_df['avg_utilization'].mean():.1%}")
        print(f"平均充電損失: {summary_df['total_charging_loss'].mean():.1f}")
    
    def run_complete_pipeline(self, config_path: str, output_file: str = 'emates_results.h5') -> int:
        """完全パイプライン実行"""
        try:
            # 1. 設定読み込み
            solutions = self.load_cs_configurations(config_path)
            
            # 2. シミュレーション実行
            sim_result = self.run_simulations(solutions)
            if sim_result != 0:
                return sim_result
            
            # 3. 結果収集と評価
            results = self.collect_and_evaluate_results()
            
            # 4. 結果保存
            if results:
                self.save_results(results, output_file)
            else:
                self.logger.warning("評価結果が空です")
                return 1
            
            self.logger.info("パイプライン完了")
            return 0
            
        except Exception as e:
            self.logger.error(f"パイプライン実行エラー: {e}")
            return 1

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='eMATES統合パイプライン')
    parser.add_argument('-p', '--parallel', type=int, default=4,
                        help='並列実行数 (デフォルト: 4)')
    parser.add_argument('-c', '--config', type=str, required=True,
                        help='CS設定JSONファイルのパス')
    parser.add_argument('-o', '--output', type=str, default='emates_results.h5',
                        help='出力ファイル名')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='デバッグモード')
    parser.add_argument('--collect-only', action='store_true',
                        help='シミュレーション実行をスキップして収集・評価のみ実行')
    
    args = parser.parse_args()
    
    # パイプライン実行
    pipeline = EMATESPipeline(args.parallel, args.debug)
    
    if args.collect_only:
        # 収集・評価のみ
        results = pipeline.collect_and_evaluate_results()
        if results:
            pipeline.save_results(results, args.output)
            return 0
        else:
            return 1
    else:
        # 完全パイプライン
        return pipeline.run_complete_pipeline(args.config, args.output)

if __name__ == "__main__":
    sys.exit(main())
