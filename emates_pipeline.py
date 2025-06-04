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
    """eMATESシミュレーションの統合パイプライン - データ整理特化版"""
    
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
    
    def _load_T_files(self, emates_dir: Path, start_datetime: str = "2024-01-01 00:00:00") -> pd.DataFrame:
        """Tファイル（時系列データ）の読み込み - datetime対応版"""
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
            
            # データフレーム結合
            combined_df = pd.concat(t_dfs, ignore_index=True)
            
            # CSIDごとにCap_kWとwaitingLineを集約
            cap_kw_df, waiting_df = self._aggregate_cs_data_separated(combined_df)
            
            # 分離版でもdatetime変換を適用
            cap_kw_df = self._add_datetime_index(cap_kw_df, start_datetime)
            waiting_df = self._add_datetime_index(waiting_df, start_datetime)
            
            return {"cap_kw": cap_kw_df, "waiting_line": waiting_df}
                
        except Exception as e:
            self.logger.warning(f"Tファイル読み込みエラー: {e}")
            return pd.DataFrame()

    def _add_datetime_index(self, df: pd.DataFrame, start_datetime: str) -> pd.DataFrame:
        """DataFrameにdatetimeインデックスを追加"""
        if df.empty or 'ElapsedTime' not in df.columns:
            return df
        
        try:
            # 開始時刻を基準にしたdatetimeインデックス作成
            start_time = pd.to_datetime(start_datetime)
            
            # ElapsedTimeを秒単位と仮定してTimedeltaに変換
            df['Timestamp'] = start_time + pd.to_timedelta(df['ElapsedTime'], unit='s')
            
            # Timestampをインデックスに設定
            df = df.set_index('Timestamp')
            df = df.sort_index()
            
            self.logger.info(f"datetime変換完了: {len(df)}行, 期間: {df.index.min()} - {df.index.max()}")
            
            return df
            
        except Exception as e:
            self.logger.warning(f"datetime変換エラー: {e}")
            return df
    
    def _aggregate_cs_data_separated(self, df: pd.DataFrame) -> tuple:
        """CSIDごとのデータを時間ごとに集約（分離版）"""
        try:
            # Cap_kWとwaitingLineを別々のDataFrameとして作成
            cap_kw_df = df.pivot_table(
                index='ElapsedTime',
                columns='Csid',
                values='Cap_kW',
                fill_value=0
            )
            cap_kw_df.columns = [f'CS_{csid}' for csid in cap_kw_df.columns]
            
            waiting_df = df.pivot_table(
                index='ElapsedTime',
                columns='Csid',
                values='waitingLine',
                fill_value=0
            )
            waiting_df.columns = [f'CS_{csid}' for csid in waiting_df.columns]
            
            # ElapsedTimeを列として復元
            cap_kw_df = cap_kw_df.reset_index()
            waiting_df = waiting_df.reset_index()
            
            self.logger.info(f"CS集約完了（分離版）: Cap_kW {cap_kw_df.shape}, waitingLine {waiting_df.shape}")
            
            return cap_kw_df, waiting_df
            
        except Exception as e:
            self.logger.warning(f"CS集約エラー（分離版）: {e}")
            return pd.DataFrame(), pd.DataFrame()


    def _resample_timeseries(self, df: pd.DataFrame, freq: str = '1H') -> pd.DataFrame:
        """時系列データのリサンプリング（補間用）"""
        if df.empty or not isinstance(df.index, pd.DatetimeIndex):
            return df
        
        try:
            # 数値カラムのみを対象にリサンプリング
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            
            if len(numeric_cols) == 0:
                return df
            
            # 数値データを平均でリサンプリング
            resampled = df[numeric_cols].resample(freq).mean()
            
            # 非数値データは最初の値で前方補完
            categorical_cols = df.select_dtypes(exclude=[np.number]).columns
            if len(categorical_cols) > 0:
                categorical_resampled = df[categorical_cols].resample(freq).first()
                resampled = pd.concat([resampled, categorical_resampled], axis=1)
            
            # 欠損値の補間
            resampled = resampled.interpolate(method='linear')
            
            self.logger.info(f"リサンプリング完了: {freq} 間隔, {len(resampled)}行")
            return resampled
            
        except Exception as e:
            self.logger.warning(f"リサンプリングエラー: {e}")
            return df

    def _load_worker_data(self, worker_id: int, result_dir: Path, 
                        start_datetime: str = "2024-01-01 00:00:00",
                        resample_freq: Optional[str] = None) -> Dict:
        """単一ワーカーのデータ読み込み - datetime対応版"""
        emates_dir = result_dir / "emates"
        
        # 時系列データ（Tファイル）- datetime変換
        t_data = self._load_T_files(emates_dir, start_datetime)
        
        # 必要に応じてリサンプリング
       # if resample_freq:
       #     t_data = self._resample_timeseries(t_data.get('cap_kw'), resample_freq)
            
        
        # 充電ロスデータ
        charging_loss = self._load_charging_loss(result_dir)
        
        # 走行データ
        vehicle_trip = self._load_vehicle_trip(result_dir)
        
        return {
            "worker_id": worker_id,
            "result_dir": result_dir,
            "timeseries": t_data,
            "charging_loss": charging_loss,
            "vehicle_trip": vehicle_trip,
            "start_datetime": start_datetime
        }

    def collect_worker_data(self, max_workers: int = 100, 
                           start_datetime: str = "2024-01-01 00:00:00",
                           resample_freq: Optional[str] = None) -> Dict[str, Dict]:
        """ワーカーデータの収集・整理のみ実行"""
        self.logger.info("データ収集・整理を開始（datetime対応）")
        
        worker_data_collection = {}
        
        for worker_id in range(1, max_workers + 1):
            try:
                paths = get_paths(worker_id)
                result_dir = Path(paths["res"])
                
                if not result_dir.exists():
                    self.logger.info(f"Worker {worker_id} が見つからないため処理終了")
                    break
                
                # データ収集（datetime対応）
                worker_data = self._load_worker_data(
                    worker_id, result_dir, start_datetime, resample_freq
                )
                
                worker_data_collection[f"worker_{worker_id}"] = worker_data
                
            except Exception as e:
                self.logger.error(f"Worker {worker_id} データ収集エラー: {e}")
                continue
        
        self.logger.info(f"総計 {len(worker_data_collection)} ワーカーのデータを収集")
        return worker_data_collection
    
    def _load_charging_loss(self, result_dir: Path) -> pd.DataFrame:
        """充電ロスデータの読み込み"""
        try:
            charging_loss_path = result_dir / "chargingLoss.txt"
            if not charging_loss_path.exists():
                return pd.DataFrame()
            
            df = pd.read_csv(
                charging_loss_path, sep=',',header=None,
                names=['Time', 'EVID', 'CSID', 'WaitingNum', 'NumPorts', 'SOC'],
                dtype = {'Time': 'int64','EVID': 'int64','CSID': 'int64',
                    'WaitingNum': 'int64','NumPorts': 'int64',
                    'SOC': 'float64'}
            )
            # 時間をmsから秒に変換
            df['Time_sec'] = df['Time'] / 1000
            
            # 60秒間隔にビニング
            df['ElapsedTime'] = (df['Time_sec'] // 60) * 60
            df.drop(columns=['Time_sec','Time'], inplace=True)
            df = self._add_datetime_index(df, "2024-01-01 00:00:00")
            return df
        
        except Exception as e:
            self.logger.warning(f"充電ロスデータ読み込みエラー: {e}")
            return pd.DataFrame()
    
    def _load_vehicle_trip(self, result_dir: Path) -> pd.DataFrame:
        """走行データの読み込み"""
        try:
            vehicle_trip_path = result_dir / "vehicleTrip.txt"
            if not vehicle_trip_path.exists():
                return pd.DataFrame()
            
            df = pd.read_csv(
                vehicle_trip_path, sep=r',',usecols=[0, 2, 3, 4, 5, 8,9,10,11, 14],
                names=['EVID','StartTime', 'EndTime', 'WaitingEntryTime','startChargingTime',
                       'startID','goalID','tripLength','CSID', 'InitialSOC']
            )
            df.fillna({'CSID':9999}, inplace=True)  # CSIDがNaNの場合は9999で埋める
            
            return df
            
        except Exception as e:
            self.logger.warning(f"走行データ読み込みエラー: {e}")
            return pd.DataFrame()
    
    def run_data_collection_pipeline(self, config_path: Optional[str] = None) -> Dict[str, Dict]:
        """データ収集パイプライン実行"""
        try:
            # シミュレーション実行（設定ファイルが指定された場合のみ）
            if config_path:
                solutions = self.load_cs_configurations(config_path)
                sim_result = self.run_simulations(solutions)
                if sim_result != 0:
                    raise RuntimeError("シミュレーション実行に失敗")
            
            # データ収集と整理
            worker_data = self.collect_worker_data()
            
            if worker_data:
                self.logger.info("データ収集パイプライン完了")
                return worker_data
            else:
                self.logger.warning("収集されたデータが空です")
                return {}
            
        except Exception as e:
            self.logger.error(f"データ収集パイプライン実行エラー: {e}")
            return {}
        
def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='eMATESデータ収集パイプライン')
    parser.add_argument('-p', '--parallel', type=int, default=4,
                        help='並列実行数 (デフォルト: 4)')
    parser.add_argument('-c', '--config', type=str,
                        help='CS設定JSONファイルのパス（省略時はデータ収集のみ）')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='デバッグモード')
    parser.add_argument('--collect-only', action='store_true',
                        help='シミュレーション実行をスキップしてデータ収集のみ実行')
    
    args = parser.parse_args()
    
    # パイプライン実行
    pipeline = EMATESPipeline(args.parallel, args.debug)
    
    if args.collect_only:
        # データ収集のみ
        worker_data = pipeline.collect_worker_data()
        if worker_data:
            print(f"\n収集完了: {len(worker_data)} ワーカーのデータを収集しました")
            # データフレームの基本情報を表示
            for worker_name, data in worker_data.items():
                print(f"{worker_name}: 時系列データ {len(data['timeseries'])}行")
            return 0
        else:
            return 1
    else:
        # 完全パイプライン（シミュレーション実行 + データ収集）
        worker_data = pipeline.run_data_collection_pipeline(args.config)
        if worker_data:
            print(f"\nパイプライン完了: {len(worker_data)} ワーカーのデータを収集しました")
            return 0
        else:
            return 1

if __name__ == "__main__":
    sys.exit(main())
    
