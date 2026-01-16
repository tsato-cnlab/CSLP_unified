import time
import logging
import subprocess

# プロセス管理用クラス
class SimulationProcess:
    """シミュレーションプロセスを管理するクラス"""
    
    def __init__(self, worker_id, command, log_interval=60):
        self.worker_id = worker_id
        self.command = command
        self.log_interval = log_interval
        self.start_time = time.time()
        self.last_log_time = self.start_time
        
    def should_log_progress(self):
        """進捗ログを出力すべきか判断"""
        current_time = time.time()
        if current_time - self.last_log_time > self.log_interval:
            self.last_log_time = current_time
            return True
        return False
        
    def log_progress(self):
        """現在の進捗を記録"""
        elapsed = time.time() - self.start_time
        logging.info(f"ワーカー {self.worker_id}: 実行中... (経過時間: {elapsed:.1f}秒)")
        
def execute_wsl_command(command, worker_id, process):
    """WSLコマンドを実行し、出力を監視"""
    with subprocess.Popen(['wsl'] + command.split(), 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE, 
                         text=True, 
                         bufsize=1, 
                         universal_newlines=True) as proc:
        
        # 標準出力の監視
        for line in proc.stdout:
            if any(keyword in line for keyword in ["ERROR", "WARN", "progress"]):
                logging.debug(f"ワーカー {worker_id}: {line.strip()}")
            
            # 定期的な進捗報告
            if process.should_log_progress():
                process.log_progress()
        
        # プロセスの終了を待つ
        proc.wait()
        status = proc.returncode
        stderr_output = proc.stderr.read()
        
        # 結果の確認
        if status != 0:
            logging.error(f"ワーカー {worker_id} のエラー内容: {stderr_output}")
            
        return status
    
