#!/usr/bin/env python3
"""
适配 webui 脚本的路径：.aqe-output → qa/webui
"""
import re
from pathlib import Path

def adapt_paths(file_path: Path):
    """替换文件中的路径"""
    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        print(f"[SKIP] Cannot decode {file_path}")
        return False

    original = content

    # 1. .aqe-output/webui-session → qa/webui/session
    content = re.sub(r"\.aqe-output/webui-session", "qa/webui/session", content)
    content = re.sub(r"'\.aqe-output'", "'qa/webui'", content)
    content = re.sub(r'"\.aqe-output"', '"qa/webui"', content)

    # 2. webui-shared-assets → shared_assets
    content = content.replace('webui-shared-assets', 'shared_assets')

    # 3. current-webui-session.json → current_session.json
    content = content.replace('current-webui-session.json', 'current_session.json')

    # 4. .aqe_session_sentinel.json → .session_sentinel.json
    content = content.replace('.aqe_session_sentinel.json', '.session_sentinel.json')

    if content != original:
        file_path.write_text(content, encoding='utf-8')
        print(f"[MODIFIED] {file_path}")
        return True
    return False

def main():
    webui_dir = Path('qa_agent/webui')

    changed_files = []
    for py_file in webui_dir.rglob('*.py'):
        if adapt_paths(py_file):
            changed_files.append(py_file)

    print(f"[OK] Path adaptation completed, {len(changed_files)} files modified:")
    for f in changed_files:
        print(f"  - {f}")

if __name__ == '__main__':
    main()
