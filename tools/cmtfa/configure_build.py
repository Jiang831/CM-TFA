#!/usr/bin/env python3
"""Configure the Android SDK and package ID for the ClashMeta-T test APK."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

EXPECTED_VERSION = '2.11.37'
APPLICATION_ID = 'com.jiang831.cmtfa'


def configure(root: Path) -> None:
    build_file = root / 'build.gradle.kts'
    content = build_file.read_text(encoding='utf-8')
    if not re.search(r'versionName\s*=\s*"' + re.escape(EXPECTED_VERSION) + r'"', content):
        raise RuntimeError('Stopped: source is not the pinned CMFA v2.11.37 baseline')
    sdk = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
    if not sdk or not Path(sdk).is_dir():
        raise RuntimeError('Stopped: Android SDK path not available on CI runner')
    local = root / 'local.properties'
    if local.exists():
        raise RuntimeError('Stopped: local.properties already exists; will not overwrite user configuration')
    local.write_text('sdk.dir=' + sdk.replace('\\', '\\\\') + '\n'
                     + 'custom.application.id=' + APPLICATION_ID + '\n'
                     + 'remove.suffix=true\n', encoding='utf-8')
    print('Prepared ClashMeta-T ' + EXPECTED_VERSION)
    print('Application ID: ' + APPLICATION_ID)
    print('Signing: repository Gradle default test signing (not production release)')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--repo-root', type=Path, default=Path.cwd())
    args = p.parse_args()
    configure(args.repo_root.resolve())
