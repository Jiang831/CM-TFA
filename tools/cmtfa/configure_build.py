#!/usr/bin/env python3
"""Prepare an independently installable CM-TFA test APK from CMFA v2.11.37.

Changes are made to the CI checkout only; the source main branch is untouched.
This deliberately does NOT enable Tailscale inbound listeners.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

EXPECTED_VERSION = '2.11.37'
APPLICATION_ID = 'com.jiang831.cmtfa'
APP_LABEL = 'CM-TFA'


def configure(root: Path) -> None:
    build_file = root / 'build.gradle.kts'
    content = build_file.read_text(encoding='utf-8')
    if not re.search(r'versionName\s*=\s*"' + re.escape(EXPECTED_VERSION) + r'"', content):
        raise RuntimeError('Stopped: source is not the pinned CMFA v2.11.37 baseline')
    alpha_start = content.index('            create("alpha") {')
    meta_start = content.index('            create("meta") {', alpha_start)
    prefix, alpha, suffix = content[:alpha_start], content[alpha_start:meta_start], content[meta_start:]
    mapping = {
        'resValue("string", "launch_name", "@string/launch_name_alpha")': 'resValue("string", "launch_name", "' + APP_LABEL + '")',
        'resValue("string", "application_name", "@string/application_name_alpha")': 'resValue("string", "application_name", "' + APP_LABEL + '")',
    }
    for src, target in mapping.items():
        count = alpha.count(src)
        if count != 1:
            raise RuntimeError(f'Stopped: expected exactly 1 occurrence of {src}, got {count}')
        alpha = alpha.replace(src, target, 1)
    build_file.write_text(prefix + alpha + suffix, encoding='utf-8')

    sdk = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
    if not sdk or not Path(sdk).is_dir():
        raise RuntimeError('Stopped: Android SDK path not available on CI runner')
    local = root / 'local.properties'
    if local.exists():
        raise RuntimeError('Stopped: local.properties already exists; will not overwrite user configuration')
    local.write_text('sdk.dir=' + sdk.replace('\\', '\\\\') + '\n'
                     + 'custom.application.id=' + APPLICATION_ID + '\n'
                     + 'remove.suffix=true\n', encoding='utf-8')
    print('Prepared ' + APP_LABEL + ' baseline: ' + EXPECTED_VERSION)
    print('Application ID: ' + APPLICATION_ID)
    print('Signing: repository Gradle default test signing (not production release)')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--repo-root', type=Path, default=Path.cwd())
    args = p.parse_args()
    configure(args.repo_root.resolve())
