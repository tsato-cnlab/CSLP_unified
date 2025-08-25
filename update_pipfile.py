import re

pipfile_path = 'requirements.txt'
new_lines = []
in_packages_section = False

print(f"Reading {pipfile_path}...")

# ファイルを '' として読み込む
with open(pipfile_path, 'r', encoding='utf-8') as f:
    for line in f:
        # [packages] セクションに入ったことを検知
        if line.strip() == '[packages]':
            in_packages_section = True
        # 他のセクション（[dev-packages]など）に入ったら検知をオフ
        elif line.strip().startswith('['):
            in_packages_section = False

        # [packages] セクション内で、'=' を含む行だけを対象にする
        if in_packages_section and '=' in line:
            # バージョン指定部分 "..." を "*" に置換
            modified_line = re.sub(r'(\s*=\s*)".*"', r'\1"*"', line)
            new_lines.append(modified_line)
        else:
            new_lines.append(line)

# ファイルを標準的な 'utf-8' で書き出す
with open(pipfile_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Pipfile has been updated successfully!")
print("All package versions are now set to '*'")