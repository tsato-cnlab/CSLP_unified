"""シミュレーションデータ読み込みモジュール

設計意図:
- SimulationResultデータクラスを使用して型安全性を確保
- 純粋関数として実装（副作用なし）
- pandasの効率的な操作を活用
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pickle
from typing import Tuple, List

# プロジェクトルートをパスに追加
project_root = Path.cwd().parent
sys.path.append(str(project_root))

from src.util.path_manager import get_paths
from src.simulation.simulation_result import SimulationResult, TimeSeriesData

# 定数（設計意図: マジックナンバーを排除）
TARGET_CANDIDATES = 8  # 候補地の数


def save_data_to_pickle(filename: str, worker_id: int = None) -> None:
    """シミュレーション結果をpickle形式で保存

    設計意図:
    - SimulationResultオブジェクトをそのまま保存
    - dataclassは自動的にシリアライズ可能
    """
    result_emates = load_worker_data(worker_id)
    with open(filename, 'wb') as f:
        # SimulationResultをそのまま保存（dataclassなので互換性あり）
        pickle.dump(result_emates, f)

def load_worker_data(worker_id: int = None) -> SimulationResult:
    """ワーカーデータを読み込んでSimulationResultを返す

    設計意図:
    - 辞書ではなくSimulationResultを返すことで型安全性を確保
    - 呼び出し側でキー名のタイポを防ぐ
    - IDEの補完機能が使える

    Args:
        worker_id: ワーカーID（Noneの場合はメインワーカー）

    Returns:
        SimulationResult: 全シミュレーション結果を含むオブジェクト
    """
    paths = get_paths(worker_id) if worker_id else get_paths()
    result_dir = Path(paths["result"])
    all_candidate_csids = [900000 + i * 2 for i in range(TARGET_CANDIDATES)]

    ts_data = load_timeseries_data(result_dir / "emates", all_candidate_csids)

    # SimulationResultオブジェクトを生成（型チェック・バリデーション付き）
    return SimulationResult(
        time_series_kw=ts_data.cap_kw,
        waiting_line=ts_data.waiting_line,
        vehicle_trip=load_vehicle_trip(result_dir),
        charging_loss=load_charging_loss(result_dir),
        cs_config=load_cs_config(worker_id)
    )

def load_timeseries_data(emates_dir: Path, all_candidate_csids: List[int]) -> TimeSeriesData:
    """候補地すべてを含む時系列データ読み込み

    設計意図:
    - タプルではなくTimeSeriesDataを返して名前付きフィールド化
    - 型ヒントで戻り値の構造を明示
    """
    """候補地すべてを含む時系列データ読み込み"""

    t_files = sorted(emates_dir.glob("T*.csv"))

    dfs = []
    for f in t_files:
        df = pd.read_csv(f)
        elapsed = int(f.stem[1:])  # T123456 -> 123456
        df['ElapsedTime'] = elapsed
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    # ピボットで集約（既存データ）
    cap_kw = combined.pivot_table(
        index='ElapsedTime',
        columns='Csid',
        values='Cap_kW',
        fill_value=0
    )

    waiting_line = combined.pivot_table(
        index='ElapsedTime',
        columns='Csid',
        values='waitingLine',
        fill_value=0
    )

    # 候補地統合（既存データ）
    cap_kw_integrated = integrate_csid_data(cap_kw)
    cap_kw_integrated = integrate_csid_data_extended(cap_kw_integrated, all_candidate_csids)
    waiting_line_integrated = integrate_csid_data(waiting_line)
    waiting_line_integrated = integrate_csid_data_extended(waiting_line_integrated, all_candidate_csids)

    # TimeSeriesDataオブジェクトを返す（設計意図: タプルより型安全）
    return TimeSeriesData(
        cap_kw=sort_columns_by_csid(cap_kw_integrated),
        waiting_line=sort_columns_by_csid(waiting_line_integrated)
    )

def integrate_csid_data_extended(time_series_df: pd.DataFrame, all_candidate_csids: list) -> pd.DataFrame:
    """候補地すべてを含むCSID統合"""

    # 時間インデックスを取得
    time_index = time_series_df.index

    # 結果DataFrame初期化
    extended_df = pd.DataFrame(time_series_df, index=time_index)
    extended_df.head()
    for candidate_csid in all_candidate_csids:
        base_csid = candidate_csid

        # 実際のCSIDグループを探索
        matching_cols = []
        for col in extended_df.columns:
            if int(col) == base_csid:
                matching_cols.append(col)
        if matching_cols:
            # 実際のデータが存在する場合
            extended_df[str(base_csid)] = extended_df[matching_cols].sum(axis=1)
        else:
            # データが存在しない場合：ダミーデータ生成
            dummy_data = pd.Series(np.nan, index=time_index)
            extended_df[str(base_csid)] = dummy_data

    return extended_df

# ✅ CSIDの大きさ順に並べ替える関数
def sort_columns_by_csid(df: pd.DataFrame) -> pd.DataFrame:
    """CSIDの大きさ順にカラムを並べ替え"""

    # カラム名を整数に変換してソート
    sorted_columns = sorted(df.columns, key=lambda x: int(x))

    # 並べ替えてDataFrameを返す
    return df[sorted_columns]

# cap_kwとwaiting_lineを並べ替え



def integrate_csid_data(time_series_df: pd.DataFrame) -> pd.DataFrame:
    """CSID統合"""
    csid_groups = {}
    for col in time_series_df.columns:
        base_csid = (int(col) // 100)
        if base_csid not in csid_groups:
            csid_groups[base_csid] = []
        csid_groups[base_csid].append(col)

    integer_cs_df = pd.DataFrame(index=time_series_df.index)
    for base_csid, cols in csid_groups.items():
        integer_cs_df[str(base_csid)] = time_series_df[cols].sum(axis=1)

    return integer_cs_df



def load_vehicle_trip(result_dir: Path) -> pd.DataFrame:
    """走行データの読み込み"""
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

    # 時間をmsから秒に変換
    time_cols = ['StartTime', 'EndTime', 'WaitingEntryTime', 'startChargingTime']
    for col in time_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce') / 1000

    return df

def load_charging_loss( result_dir: Path) -> pd.DataFrame:
    """充電ロスデータの読み込み"""
    charging_loss_path = result_dir / "chargingLoss.txt"

    df = pd.read_csv(
        charging_loss_path, sep=',',header=None,
        names=['Time', 'EVID', 'CSID', 'WaitingNum', 'NumPorts', 'SOC']
    )
    # 時間をmsから秒に変換
    df['Time_sec'] = df['Time'] / 1000

    # 60秒間隔にビニング
    df['ElapsedTime'] = (df['Time_sec'] // 60) * 60
    df.drop(columns=['Time_sec','Time'], inplace=True)
    return df

def load_cs_config(worker_id: int) -> dict:
    """CS設定読み込み"""
    paths = get_paths(worker_id)
    cs_info = pd.read_csv(
        paths["csList"],
        header=None,
        names=['CSID', 'Port', 'Cap_kw']
    )

    return {
        'csids': cs_info['CSID'].tolist(),
        'ports': cs_info['Port'].tolist(),
        'cap_kw': cs_info['Cap_kw'].tolist(),
    }

