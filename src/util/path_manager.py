import os

def get_paths(worker_id=None):
    """
    パス情報を取得する関数
    worker_idが指定された場合は並列処理用のパスを生成
    """
    # ベースパスの定義
    base = r"\\wsl.localhost\ubuntu-22.04\home\tsato-cnlab\Emates"
    
    # 通常のパス構造
    paths = {
        "shikata": os.path.join(base, r"eMATES_2308\network\coupled_network_shikata"),
        "dss": os.path.join(base, r"Evaluation_Function\ev-charging-evaluation\src")
    }
    
    # 依存パスの設定
    paths["csList"] = os.path.join(paths["shikata"], "csList.txt")
    paths["res"] = os.path.join(paths["shikata"], "result")
    paths["init"] = os.path.join(paths["shikata"], "init.txt")
    paths["signals"] = os.path.join(paths["shikata"], "signals.txt")
    paths["chrLoss"] = os.path.join(paths["res"], "chargingLoss.txt")
    paths["trip"] = os.path.join(paths["res"], "vehicleTrip.txt")
    paths["saveData"] = os.path.join(paths["res"], "Savefile")
    paths["func"] = os.path.join(paths["dss"], "function")

    
    # 並列処理ではない場合、通常のパスを返す
    if worker_id is None or worker_id == 0:
        return paths
    
    # 並列処理の場合、worker_idに基づいてパスを生成
    worker_paths = paths.copy()
    
    # shikata パスを連番付きに変更
    worker_paths["shikata"] = f"{paths['shikata']}_{worker_id}"
    
    # 依存するパスも更新
    worker_paths["csList"] = os.path.join(worker_paths["shikata"], "csList.txt")
    worker_paths["res"] = os.path.join(worker_paths["shikata"], "result")
    worker_paths["init"] = os.path.join(worker_paths["shikata"], "init.txt")
    worker_paths["signals"] = os.path.join(worker_paths["shikata"], "signals.txt")
    worker_paths["chrLoss"] = os.path.join(worker_paths["res"], "chargingLoss.txt")
    worker_paths["trip"] = os.path.join(worker_paths["res"], "vehicleTrip.txt")
    worker_paths["saveData"] = os.path.join(worker_paths["res"], "Savefile")
    worker_paths["init"] = os.path.join(worker_paths["shikata"], "init.txt")
    
    return worker_paths

def convert_to_wsl_path(windows_path):
    """WindowsパスをWSLパスに変換"""
    path = windows_path.replace('\\', '/')
    return path.replace('//wsl.localhost/ubuntu-22.04', '')