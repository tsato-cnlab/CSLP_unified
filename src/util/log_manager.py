import os
import logging
import time


# ロギングの設定
def setup_logging(debug_mode=False):
    """ログ機能のセットアップ"""
    log_level = logging.DEBUG if debug_mode else logging.INFO
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    
    # ログファイルの設定
    log_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # 実行日時をファイル名に含める
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f'simulation_{timestamp}.log')
    
    # ロガーの基本設定
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()  # コンソールにも出力
        ]
    )
    
    logging.info(f"ログ記録を開始しました: {log_file}")
    return log_file
