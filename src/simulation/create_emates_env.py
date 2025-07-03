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
        updated_lines = self._update_cs_counts(lines)
        self._write_cs_list_file(updated_lines)
        
    def _read_cs_list_file(self):
        """CSリストファイルを読み込む内部メソッド"""
        with open(self.csList_txtfile, 'r') as file:
            return file.readlines()
        
        
    def _update_cs_counts(self, lines):
        """CS数を設定に基づいて更新する内部メソッド"""
        updated = []
        # cs_configから設定を取得
        csids = self.cs_config.get('csids', [])
        ports = self.cs_config.get('ports', [])
        cap_kw = self.cs_config.get('cap_kw', [])
        
        for i in range(len(csids)):
            csid = csids[i]
            port = ports[i]
            cap = cap_kw[i]
            
            # CSIDの行を更新
            updated.append(f"{csid},{port},{cap}\n")
        return updated
        
    def _write_cs_list_file(self, lines):
        """CSリストファイルに書き込む内部メソッド"""
        csList_file_parallel = os.path.join(self.target_dir, "csList.txt")
        with open(csList_file_parallel, 'w') as file:
            for line in lines:
                file.write(line)
            
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
                self.update_cs_list()
                logging.info(f"Worker {i}のディレクトリは既に存在: {self.target_dir}")


            
def prepare_parallel_environment(parallel_count, cs_config):
    """
    並列処理のための環境を準備する関数.独立した入出力フォルダの作成のために制作。
    仮に単体のシミュレーションを行いたい場合は，parallel_countを1にして実行すれば良い。
    """
    env = ParallelEnvironment(parallel_count, cs_config)
    env.update_shikata_dir()
        
import sys
import traceback

def main():
    """メイン処理とエラーハンドリング"""
    try:
        print("=== 並列環境セットアップ開始 ===")
        
        # パラメータ設定
        parallel_count = 1
        cs_config = {
            "csids": [1, 2, 3],
            "ports": [1, 2, 3],
            "cap_kw": [50, 75, 100]
        }
        
        print(f"並列数: {parallel_count}")
        print(f"設定: {cs_config}")
        
        # 環境準備の実行
        print("環境準備中...")
        prepare_parallel_environment(parallel_count, cs_config)
        
        # 成功確認
        print("✓ 環境準備が完了しました")
        print("=== セットアップ正常終了 ===")
        
        return True
        
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        print("詳細なエラー情報:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)