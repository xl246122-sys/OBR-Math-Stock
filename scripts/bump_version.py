"""Increment APK and Backend version by +0.1 automatically.

Usage:
    python scripts/bump_version.py --check
    python scripts/bump_version.py --bump
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def get_current_versions():
    gradle_path = ROOT / "android/app/build.gradle.kts"
    content = gradle_path.read_text(encoding="utf-8")
    vc_match = re.search(r'versionCode\s*=\s*(\d+)', content)
    vn_match = re.search(r'versionName\s*=\s*"([^"]+)"', content)
    if not vc_match or not vn_match:
        raise ValueError("Could not parse versionCode or versionName from build.gradle.kts")
    code = int(vc_match.group(1))
    name = vn_match.group(1)
    return code, name


def calculate_next_version(name: str, code: int):
    parts = [int(p) for p in name.split(".")]
    if len(parts) == 2:
        parts.append(0)
    # bump minor by +1 (effectively +0.1)
    major, minor, patch = parts[0], parts[1], parts[2]
    next_minor = minor + 1
    next_patch = 0
    next_name = f"{major}.{next_minor}.{next_patch}"
    next_code = code + 1
    return next_name, next_code


def update_all_files(old_name: str, old_code: int, new_name: str, new_code: int):
    # 1. android/app/build.gradle.kts
    gradle_path = ROOT / "android/app/build.gradle.kts"
    txt = gradle_path.read_text(encoding="utf-8")
    txt = re.sub(r'versionCode\s*=\s*\d+', f'versionCode = {new_code}', txt)
    txt = re.sub(r'versionName\s*=\s*"[^"]+"', f'versionName = "{new_name}"', txt)
    gradle_path.write_text(txt, encoding="utf-8")

    # 2. android/app/src/main/java/com/obrmath/monitor/Data.kt
    data_kt = ROOT / "android/app/src/main/java/com/obrmath/monitor/Data.kt"
    if data_kt.exists():
        txt = data_kt.read_text(encoding="utf-8")
        txt = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{new_name}"', txt)
        data_kt.write_text(txt, encoding="utf-8")

    # 3. pyproject.toml
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():
        txt = pyproject.read_text(encoding="utf-8")
        txt = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{new_name}"', txt)
        pyproject.write_text(txt, encoding="utf-8")

    # 4. app/api.py
    api_py = ROOT / "app/api.py"
    if api_py.exists():
        txt = api_py.read_text(encoding="utf-8")
        txt = re.sub(r'"version":\s*"[^"]+"', f'"version": "{new_name}"', txt)
        api_py.write_text(txt, encoding="utf-8")

    # 5. app/runtime.py
    runtime_py = ROOT / "app/runtime.py"
    if runtime_py.exists():
        txt = runtime_py.read_text(encoding="utf-8")
        txt = re.sub(r'"version":\s*"[^"]+"', f'"version": "{new_name}"', txt)
        runtime_py.write_text(txt, encoding="utf-8")

    # 6. app/static/index.html
    index_html = ROOT / "app/static/index.html"
    if index_html.exists():
        old_major_minor = ".".join(old_name.split(".")[:2])
        new_major_minor = ".".join(new_name.split(".")[:2])
        txt = index_html.read_text(encoding="utf-8")
        txt = txt.replace(f"V{old_major_minor}", f"V{new_major_minor}")
        index_html.write_text(txt, encoding="utf-8")


def main():
    code, name = get_current_versions()
    next_name, next_code = calculate_next_version(name, code)
    if "--check" in sys.argv or len(sys.argv) == 1:
        print(f"Current APK version: {name} (versionCode: {code})")
        print(f"Next (+0.1) version: {next_name} (versionCode: {next_code})")
        return
    if "--bump" in sys.argv:
        update_all_files(name, code, next_name, next_code)
        print(f"Successfully bumped APK version: {name} -> {next_name} (versionCode: {code} -> {next_code})")


if __name__ == "__main__":
    main()
