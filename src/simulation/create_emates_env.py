import os
import sys
import glob
import shutil
import logging

# プロジェクトのルートディレクトリをパスに追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root)

# シンプルに直接インポート
from src.util.path_manager import get_paths, convert_to_wsl_path

class ParallelEnvironment:
    """並列シミュレーション環境を準備するクラス
    
    このクラスは、複数の独立したシミュレーションを並列実行するための
    環境を準備します。
    
    Attributes:
        parallel_count (int): 並列実行数
        cs_config (list): 充電ステーション構成
    """
    def __init__(self, parallel_count, cs_config):
        # パス獲得
        self.paths = get_paths()
        self.orig_dir = self.paths["shikata"]
        self.sign_txtfile = os.path.join(self.orig_dir, "signals")
        self.csList_txtfile = os.path.join(self.orig_dir, "csList.txt")
        self.init_txtfile = os.path.join(self.orig_dir, "init.txt")
        
        self.parallel_count = parallel_count
        self.cs_config = cs_config
        
    # 並列用のフォルダ作成関数                
    def create_parallel_dir(self):                
        os.makedirs(self.target_dir, exist_ok=True)
        os.makedirs(os.path.join(self.target_dir, "result"), exist_ok=True)
        os.makedirs(os.path.join(self.target_dir, "result", "emates"), exist_ok=True)
        os.makedirs(os.path.join(self.target_dir, "result", "inst"), exist_ok=True)
        os.makedirs(os.path.join(self.target_dir, "result", "opendss"), exist_ok=True)

    
    # 必要な入出力ファイルのコピー
    def copy_to_parallel_dir(self):
        # signalsフォルダを並列フォルダにコピー
        target_sign_folder = os.path.join(self.target_dir, "signals")
        shutil.copytree(self.sign_txtfile, target_sign_folder)
        # 入出力txtファイルを並列フォルダにコピー
        txt_files = glob.glob(os.path.join(self.orig_dir, "*.txt"))
        for src_file in txt_files:
            file_name = os.path.basename(src_file)
            dst_file = os.path.join(self.target_dir, file_name)
            shutil.copy2(src_file, dst_file)   
    
    # init.txtfileの入出力パス変更関数
    def update_init_txtfile(self):
        init_file_palarell = os.path.join(self.target_dir, "init.txt")
        with open(init_file_palarell, 'r', encoding='utf-8', errors='ignore') as file:
            lines = file.readlines()
        updated_lines = []
        #特定の行を見つけたら、パスを変更
        for line in lines:
            if line.strip().startswith('EV_COMM_COMMON_DIRECTORY'):
                updated_lines.append(f'EV_COMM_COMMON_DIRECTORY={self.wsl_path_init_txtfile}\n') # \\\\=\と認識
            else:
                # それ以外はそのまま
                updated_lines.append(line)
        with open(init_file_palarell, 'w', encoding='utf-8') as file:
            file.writelines(updated_lines)


    def update_cs_list(self):
        """CSリストを更新する公開メソッド"""
        lines = self._read_cs_list_file()
        filtered_lines = self._filter_comment_lines(lines)
        updated_lines = self._update_cs_counts(filtered_lines)
        self._write_cs_list_file(updated_lines)
        
    def _read_cs_list_file(self):
        """CSリストファイルを読み込む内部メソッド"""
        with open(self.csList_txtfile, 'r') as file:
            return file.readlines()
        
    def _filter_comment_lines(self, lines):
        """コメント行と空行を削除する内部メソッド"""
        filtered = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                filtered.append(line)
        return filtered
        
    def _update_cs_counts(self, filtered_lines):
        """CS数を設定に基づいて更新する内部メソッド"""
        updated = []
        for i, line in enumerate(filtered_lines):
            values = line.split(',')
            if len(values) >= 3 and i < len(self.cs_config):
                updated.append(f"{values[0]},{self.cs_config[i]},{values[2]}")
            else:
                updated.append(line)
        return updated
        
    def _write_cs_list_file(self, lines):
        """CSリストファイルに書き込む内部メソッド"""
        with open(self.csList_txtfile, 'w') as file:
            for line in lines:
                file.write(f"{line}\n")
            
    def update_shikata_dir(self):
        # 各ワーカー用にディレクトリをコピー
        for i in range(1, self.parallel_count + 1):
            self.target_dir = f"{self.orig_dir}_{i}"
            target_dir_with_slash = self.target_dir + os.sep 
            self.wsl_path_init_txtfile = convert_to_wsl_path(target_dir_with_slash)

            # ディレクトリが存在しない場合のみコピー
            if not os.path.exists(self.target_dir):
                # 並列用の処理
                self.create_parallel_dir()
                self.copy_to_parallel_dir()
                self.update_init_txtfile()
                self.update_cs_list()
                logging.info(f"Worker {i}のディレクトリ作成: {self.target_dir}")
            else:
                logging.info(f"Worker {i}のディレクトリは既に存在: {self.target_dir}")


            
def prepare_parallel_environment(parallel_count, cs_config):
    """
    並列処理のための環境を準備する関数.独立した入出力フォルダの作成のために制作。
    仮に単体のシミュレーションを行いたい場合は，parallel_countを1にして実行すれば良い。
    """
    env = ParallelEnvironment(parallel_count, cs_config)
    env.update_shikata_dir()
        
if __name__ == "__main__":
    # テスト用の並列環境を準備
    prepare_parallel_environment(2, [1, 2, 3, 4])
    print("create_emates_env.py が呼び出されました")
