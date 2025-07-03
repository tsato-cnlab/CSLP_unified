import os
import sys
import logging
import subprocess
import time
import concurrent.futures
from tqdm import tqdm

# プロジェクトルートを追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
# 相対インポートではなく、プロジェクトのルートからの絶対インポートに変更
from src.util.path_manager import get_paths, convert_to_wsl_path
from src.util.log_manager import setup_logging
from src.simulation.create_emates_env import prepare_parallel_environment
from src.util.decorators import log_execution_time

@log_execution_time
def run_single_emates_simulation(paths, worker_id):
    """
    単一のeMATESシミュレーションを実行する関数
    """
    # シミュレーション時間
    HOUR = 24  # シミュレーション時間（時間単位）
    TS_CALC = 3600 * HOUR * 1000  # 24時間シミュレーション
    
    # WSLパスに変換
    shikata_wsl = convert_to_wsl_path(paths["shikata"])    
    # 実行コマンド
    wsl_command = f'/home/tsato-cnlab/Emates/eMATES_2308/solver/advmates-calc -e 0 ' \
                  f'-d {shikata_wsl} -s ' \
                  f'--no-generate-random-vehicle -no-input-signal -r 1 -t {TS_CALC}'
    
        # 開始時刻を記録
    start_time = time.time()
    # WSLでコマンド実行
    try:
        # 標準出力をリアルタイムでキャプチャするために、Popenを使用
        with subprocess.Popen(['wsl'] + wsl_command.split(), 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE, 
                             text=True, 
                             bufsize=1, 
                             universal_newlines=True) as proc:
            
            # 進捗ロギング用のカウンタとタイマー
            last_log_time = time.time()
            log_interval = 60  # 1分ごとに進捗ログ
            
            # 標準出力をリアルタイムで読み込む
            for line in proc.stdout:
                # 重要な出力行のみをロギング
                if "ERROR" in line or "WARN" in line or "progress" in line:
                    logging.debug(f"ワーカー {worker_id}: {line.strip()}")
                
                # 定期的に進行中の報告
                current_time = time.time()
                if current_time - last_log_time > log_interval:
                    elapsed = current_time - start_time
                    logging.info(f"ワーカー {worker_id}: 実行中... (経過時間: {elapsed:.1f}秒)")
                    last_log_time = current_time
            
            # プロセスの終了を待つ
            proc.wait()
            status = proc.returncode
            
            # エラー出力を読み込む
            stderr_output = proc.stderr.read()
            
            # 終了処理
            elapsed_time = time.time() - start_time
            if status != 0:
                logging.error(f"ワーカー {worker_id} のシミュレーション失敗 (所要時間: {elapsed_time:.1f}秒)")
                logging.error(f"エラー内容: {stderr_output}")
                return status
            else:
                logging.info(f"ワーカー {worker_id} のシミュレーション完了 (所要時間: {elapsed_time:.1f}秒)")
                return 0
                
    except Exception as e:
        logging.exception(f"ワーカー {worker_id} の実行例外: {e}")
        return 1

def run_parallel_emates_simulations(base_config, parallel_count=1):
    """
    複数のeMATESシミュレーションを並列に実行する関数
    """
    logging.info(f"並列シミュレーション開始: {parallel_count}プロセス")
    
    # 開始時刻を記録
    overall_start_time = time.time()
    
    # 並列処理の前に必要なディレクトリを準備（一度だけ実行）
    try:
        prepare_parallel_environment(parallel_count, base_config)
        logging.info("並列環境の準備が完了しました")
    except Exception as e:
        logging.error(f"並列環境の準備中にエラーが発生: {e}")
        return 1
    
    # ThreadPoolExecutorの設定
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
        try:
            future_to_worker = {}
            for i in range(1, parallel_count + 1):
                worker_paths = get_paths(i)
                future = executor.submit(run_single_emates_simulation, worker_paths, i)
                future_to_worker[future] = i
            
            # 結果の収集（tqdmでラップ）
            status = [1] * parallel_count
            with tqdm(total=parallel_count, 
                    desc="シミュレーション実行中",
                    position=0,
                    leave=True) as pbar:
                for future in concurrent.futures.as_completed(future_to_worker):
                    worker_id = future_to_worker[future]
                    try:
                        worker_status = future.result()
                        status[worker_id - 1] = worker_status
                        if worker_status != 0:
                            logging.warning(f"ワーカー {worker_id} でエラー発生")
                        else:
                            logging.info(f"ワーカー {worker_id} のシミュレーション正常終了")
                    except Exception as e:
                        logging.exception(f"ワーカー {worker_id} の実行例外: {e}")
                    pbar.update(1)
        finally:
            # すべてのスレッドが終了するまで待機
            executor.shutdown(wait=True)
            logging.info("すべてのスレッドが終了しました")

    # 終了処理
    overall_elapsed_time = time.time() - overall_start_time
    
    # すべての実行が成功したか確認
    if all(s == 0 for s in status):
        logging.info(f"すべてのシミュレーションが正常に完了しました (総所要時間: {overall_elapsed_time:.1f}秒)")
        overall_status = 0
    else:
        logging.error(f"一部のシミュレーションでエラーが発生しました (総所要時間: {overall_elapsed_time:.1f}秒)")
        overall_status = 1
    
    return overall_status

if __name__ == "__main__":
    # ログ設定
    log_file = setup_logging(debug=True)
    logging.info("eMATESシミュレーションスクリプト開始")
    
    # シミュレーションの基本設定
    base_config = {
        "csids": [1, 2, 3],
        "ports": [1, 2, 3],
        "cap_kw": [50, 75, 100]
    }
    
    # 並列実行数
    parallel_count = 1
    
    # シミュレーション実行
    result = run_parallel_emates_simulations(base_config, parallel_count)
    
    logging.info(f"プログラム終了 (ステータス: {result})")
    exit(result)