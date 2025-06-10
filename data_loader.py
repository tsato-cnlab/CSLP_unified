from src.util.path_manager import get_paths
from src.util.log_manager import setup_logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
import logging
import re


class DataLoader:
    def __init__(self, debug: bool = False):
        self.debug = debug  # デバッグモードのフラグ
        self.logger = self._setup_logging()
        self.scenario_data = {}
        self.data = None
        
    def _setup_logging(self):
        """ログ設定"""
        setup_logging(self.debug)
        return logging.getLogger(__name__)
    
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
    # 並列を使う場合のデータ処理
    def collect_worker_data(self, max_workers: int = 100, 
                        start_datetime: str = "2024-01-01 00:00:00",
                        resample_freq: Optional[str] = None) -> Dict[str, Dict]:
        """ワーカーデータの収集・整理のみ実行"""
        self.logger.info("データ収集・整理を開始（datetime対応）")
        
        worker_data_collection = {}
        
        for worker_id in range(1, max_workers + 1):
            try:
                paths = get_paths(worker_id)
                result_dir = Path(paths["result"])
                
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
            cap_kw_df, waiting_line_df = self._aggregate_cs_data_separated(combined_df)
            
            # 分離版でもdatetime変換を適用
            cap_kw_df = self._add_datetime_index(cap_kw_df, start_datetime)
            waiting_line_df = self._add_datetime_index(waiting_line_df, start_datetime)
            
            cap_kw_df, waiting_line_df = self._integrate_csid_data(cap_kw_df), self._integrate_csid_data(waiting_line_df)
            
            return cap_kw_df, waiting_line_df
                
        except Exception as e:
            self.logger.warning(f"Tファイル読み込みエラー: {e}")
            return pd.DataFrame()
    
    def _get_base_csid(self, csid_str:str) -> int:
        """CSIDからベース番号を取得（末尾2桁を除去）"""
        csid = int(csid_str)
        return (csid // 100) * 100
    
    def _integrate_csid_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """同一ベースCSIDのカラムを合計して統合"""
        csid_groups = {}
        integrated_csid_df = pd.DataFrame(index=df.index)
        if "ElapsedTime" in df.columns:
            df.drop(columns=["ElapsedTime"], inplace=True)

        for csid in df.columns:
            base_csid = self._get_base_csid(csid_str = csid)
            if base_csid not in csid_groups:
                csid_groups[base_csid] = []
            csid_groups[base_csid].append(csid)
        for base_csid, cols in csid_groups.items():
            # 同一ベースCSIDのカラムを合計
            integrated_csid_df[str(base_csid)] = df[cols].sum(axis=1)
        return integrated_csid_df

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
    
    def _aggregate_cs_data_separated(self, df: pd.DataFrame) -> pd.DataFrame:
        """CSIDごとのデータを時間ごとに集約（分離版）"""
        try:
            # Cap_kWとwaitingLineを同じDataFrameとして作成
            cap_kw_df = df.pivot_table(
                index='ElapsedTime',
                columns='Csid',
                values='Cap_kW',
                fill_value=0
            )
            cap_kw_df.columns = [f'{csid}' for csid in cap_kw_df.columns]
            
            waiting_df = df.pivot_table(
                index='ElapsedTime',
                columns='Csid',
                values='waitingLine',
                fill_value=0
            )
            waiting_df.columns = [f'{csid}' for csid in waiting_df.columns]
            
            cap_kw_df.reset_index(inplace=True)
            waiting_df.reset_index(inplace=True)
                                    
            return cap_kw_df, waiting_df
            
        except Exception as e:
            self.logger.warning(f"CS集約エラー: {e}")
            return pd.DataFrame()

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
        cap_kw_df, waiting_line_df = self._load_T_files(emates_dir, start_datetime)
        
        
        # 必要に応じてリサンプリング
        if resample_freq:
            t_data = self._resample_timeseries(t_data.get('cap_kw'), resample_freq)
            
        
        # 充電ロスデータ
        charging_loss = self._load_charging_loss(result_dir)
        # 走行データ
        vehicle_trip = self._load_vehicle_trip(result_dir)
        # CSIDとポート情報の抽出
        cs_data = self._get_cs_list(worker_id)
        
        return {
            "worker_id": worker_id,
            "result_dir": result_dir,
            "time_series_kw": cap_kw_df,
            "time_series_waiting_line": waiting_line_df,
            "charging_loss": charging_loss,
            "vehicle_trip": vehicle_trip,
            "csids": cs_data['csids'],
            "ports": cs_data['ports'],
            "cap_kw": cs_data['cap_kw'],
            "total_ports": cs_data['total_ports'],
        }
    
    def _get_cs_list(self, worker_id: int) -> Dict[str, any]:
        """CSリストファイルからCS情報を取得"""
        try:
            paths = get_paths(worker_id)
            csList_file = paths["csList"]
            cs_info = pd.read_csv(csList_file, sep=',', header=None, names=['CSID', 'Port', 'Cap_kw'])
            
            # CS情報を辞書形式で整理
            cs_data = {
                'csids': cs_info['CSID'].tolist(),
                'ports': cs_info['Port'].tolist(),
                'cap_kw': cs_info['Cap_kw'].tolist(),
                'total_ports': cs_info['Port'].sum(),
                'total_cs_count': len(cs_info)
            }
            
            self.logger.info(f"Worker {worker_id}: CS情報取得完了 - {cs_data['total_cs_count']}箇所, 総ポート数: {cs_data['total_ports']}")
            return cs_data
            
        except Exception as e:
            self.logger.warning(f"Worker {worker_id} CS情報取得エラー: {e}")
            return {
                'csids': [],
                'ports': [],
                'cap_kw': [],
                'total_ports': 0,
                'total_cs_count': 0,
            }
    
    def _load_charging_loss(self, result_dir: Path) -> pd.DataFrame:
        """充電ロスデータの読み込み"""
        try:
            charging_loss_path = result_dir / "chargingLoss.txt"
            if not charging_loss_path.exists():
                return pd.DataFrame()
            
            df = pd.read_csv(
                charging_loss_path, sep=',',header=None,
                names=['Time', 'EVID', 'CSID', 'WaitingNum', 'NumPorts', 'SOC']
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
                       'startID','goalID','tripLength','CSID', 'InitialSOC'],
                dtype=str
            )
                    # 特殊文字の処理
            def clean_numeric_value(value):
                """数値変換前の前処理"""
                if pd.isna(value) or value == '' or value == '******':
                    return np.nan
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return np.nan
            
            # 各列を適切な型に変換
            numeric_columns = ['EVID', 'StartTime', 'EndTime', 'WaitingEntryTime', 
                            'startChargingTime', 'startID', 'goalID', 'tripLength', 
                            'CSID', 'InitialSOC']
            
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = df[col].apply(clean_numeric_value)
            # 時間を秒に変換
            
            df['StartTime'] = df['StartTime'] / 1000
            df['EndTime'] = df['EndTime'] / 1000
            df['WaitingEntryTime'] = df['WaitingEntryTime'] / 1000
            df['startChargingTime'] = df['startChargingTime'] / 1000
            
            return df
            
        except Exception as e:
            self.logger.warning(f"走行データ読み込みエラー: {e}")
            return pd.DataFrame()
    
        
        
        
        
if __name__ == "__main__":
    # データローダーのインスタンスを作成
    data_loader = DataLoader()
    
    # ワーカーデータの収集
    worker_data = data_loader.collect_worker_data(max_workers=10, 
                                                  start_datetime="2024-01-01 00:00:00")
    
    plandata = data_loader.collect_scenario_data(
        scenario_id=1, year=0, worker_ids=list(worker_data.keys())
    )
    # 結果を表示
    for worker_id, data in worker_data.items():
        print(f"Worker {worker_id}:")
        print(f"  Time Series (Cap_kW):\n{data['time_series_kw'].head()}")
        print(f"  Time Series (Waiting Line):\n{data['time_series_waiting_line'].head()}")
        print(f"  Charging Loss:\n{data['charging_loss'].head()}")
        print(f"  Vehicle Trip:\n{data['vehicle_trip'].head()}")
        print(f"  CSIDs: {data['csids']}")
        print(f"  Total Ports: {data['total_ports']}\n")