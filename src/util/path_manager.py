import os
import platform

def get_paths(worker_id=None):
    """
    パス情報を取得する関数
    worker_idが指定された場合は並列処理用のパスを生成
    WSL2環境に対応
    """
    # ✅ WSL2環境の判定とベースパスの設定
    if platform.system() == "Linux" and "microsoft" in platform.uname().release.lower():
        # WSL2環境
        # base = "/home/tsato-cnlab/Emates"
        base = "/home/oums/Emates"
        path_sep = "/"
    if platform.system() == "Linux":
        base = "/home/oums/Emates"
        path_sep = "/"
    else:
        # Windows環境
        base = r"\\wsl.localhost\ubuntu-22.04\home\tsato-cnlab\Emates"
        path_sep = "\\"
    
    # ✅ パス構造をWSL2対応に修正
    if platform.system() == "Linux":
        paths = {
            "shikata": os.path.join(base, "eMATES_2308", "network", "simple_shikata"),  # simple_shikataに修正
            "dss": os.path.join(base, "Evaluation_Function", "ev-charging-evaluation", "src")
        }
    else:
        paths = {
            "shikata": os.path.join(base, r"eMATES_2308\network\simple_shikata"),  # simple_shikataに修正
            "dss": os.path.join(base, r"Evaluation_Function\ev-charging-evaluation\src")
        }
    
    # 依存パスの設定
    paths["csList"] = os.path.join(paths["shikata"], "csList.txt")
    paths["result"] = os.path.join(paths["shikata"], "result")
    paths["init"] = os.path.join(paths["shikata"], "init.txt")
    paths["signals"] = os.path.join(paths["shikata"], "signals.txt")
    paths["chrLoss"] = os.path.join(paths["result"], "chargingLoss.txt")
    paths["trip"] = os.path.join(paths["result"], "vehicleTrip.txt")
    paths["saveData"] = os.path.join(paths["result"], "Savefile")
    paths["func"] = os.path.join(paths["dss"], "function")

    # # ✅ パスの存在確認とデバッグ出力
    # print(f"環境: {platform.system()}")
    # print(f"ベースパス: {base}")
    # print(f"csList.txtパス: {paths['csList']}")
    # print(f"csList.txt存在確認: {os.path.exists(paths['csList'])}")
    
    # 並列処理ではない場合、通常のパスを返す
    if worker_id is None or worker_id == 0:
        return paths
    
    # 並列処理の場合、worker_idに基づいてパスを生成
    worker_paths = paths.copy()
    
    # shikata パスを連番付きに変更
    if platform.system() == "Linux":
        worker_paths["shikata"] = f"{paths['shikata']}_{worker_id}"
    else:
        worker_paths["shikata"] = f"{paths['shikata']}_{worker_id}"
    
    # 依存するパスも更新
    worker_paths["csList"] = os.path.join(worker_paths["shikata"], "csList.txt")
    worker_paths["result"] = os.path.join(worker_paths["shikata"], "result")
    worker_paths["init"] = os.path.join(worker_paths["shikata"], "init.txt")
    worker_paths["signals"] = os.path.join(worker_paths["shikata"], "signals.txt")
    worker_paths["chrLoss"] = os.path.join(worker_paths["result"], "chargingLoss.txt")
    worker_paths["trip"] = os.path.join(worker_paths["result"], "vehicleTrip.txt")
    worker_paths["saveData"] = os.path.join(worker_paths["result"], "Savefile")
    
    return worker_paths

def convert_to_wsl_path(windows_path):
    """WindowsパスをWSLパスに変換"""
    if platform.system() == "Linux":
        # 既にLinuxパスの場合はそのまま返す
        return windows_path
    
    path = windows_path.replace('\\', '/')
    return path.replace('//wsl.localhost/ubuntu-22.04', '')

def ensure_linux_path(path):
    """パスがLinux形式であることを保証"""
    return path.replace('\\', '/')