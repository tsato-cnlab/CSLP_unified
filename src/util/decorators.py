import time
import logging
import functools


def log_execution_time(func):
    """関数の実行時間を記録するデコレータ"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        worker_id = kwargs.get('worker_id') or args[1]  # 第2引数がworker_id
        start_time = time.time()
        logging.info(f"ワーカー {worker_id} の処理開始")
        
        try:
            result = func(*args, **kwargs)
            elapsed_time = time.time() - start_time
            logging.info(f"ワーカー {worker_id} の処理完了 (所要時間: {elapsed_time:.1f}秒)")
            return result
        except Exception as e:
            elapsed_time = time.time() - start_time
            logging.exception(f"ワーカー {worker_id} の処理例外 (所要時間: {elapsed_time:.1f}秒): {e}")
            raise
            
    return wrapper