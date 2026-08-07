# -*- coding: utf-8 -*-
"""打包脚本：将项目打包为 zip 文件，自动排除 .gitignore 中的文件。"""

import os
import zipfile
import fnmatch
from pathlib import Path


def parse_gitignore(gitignore_path: Path):
    """解析 .gitignore 文件，返回排除模式列表。"""
    patterns = []
    if not gitignore_path.exists():
        return patterns
    
    with open(gitignore_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                # 去掉行尾的注释
                comment_index = line.find('#')
                if comment_index > 0:
                    line = line[:comment_index].strip()
                if line:
                    patterns.append(line)
    return patterns


def should_exclude(file_path: Path, root: Path, patterns: list) -> bool:
    """判断文件/目录是否应该被排除。"""
    relative_path = file_path.relative_to(root)
    str_path = str(relative_path).replace('\\', '/')
    
    for pattern in patterns:
        # 如果模式以 / 开头，只匹配根目录
        if pattern.startswith('/'):
            if fnmatch.fnmatch(str_path, pattern[1:]):
                return True
            # 检查是否以该模式开头（用于目录）
            if str_path.startswith(pattern[1:]):
                return True
        else:
            # 检查路径的每个部分
            parts = str_path.split('/')
            for i, part in enumerate(parts):
                if fnmatch.fnmatch(part, pattern):
                    # 如果模式匹配的是目录名，且这是目录的最后一部分或还有子目录，排除
                    if i == len(parts) - 1 or not '.' in part or fnmatch.fnmatch(str_path, f'**/{pattern}'):
                        return True
            # 也尝试直接匹配完整路径
            if fnmatch.fnmatch(str_path, pattern):
                return True
            # 检查子目录下的文件
            if fnmatch.fnmatch(str_path, f'**/{pattern}'):
                return True
    return False


def main():
    root = Path(__file__).resolve().parent
    gitignore_path = root / '.gitignore'
    patterns = parse_gitignore(gitignore_path)
    
    output_zip = root / 'MiyoQian-deploy.zip'
    if output_zip.exists():
        output_zip.unlink()
        
    print(f'开始打包，共 {len(patterns)} 条排除规则...')
    
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in root.rglob('*'):
            if file_path.is_file() and '.git' not in str(file_path.relative_to(root)):
                if not should_exclude(file_path, root, patterns):
                    arcname = file_path.relative_to(root)
                    zf.write(file_path, arcname)
    
    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f'打包完成：{output_zip} ({size_mb:.2f} MB)')
    print('请将此 zip 文件上传至服务器解压后使用。')


if __name__ == '__main__':
    main()
