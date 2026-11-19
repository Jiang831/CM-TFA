"""Apply the ClashMeta-T overlays to an official CMFA release and build an ARM64 APK."""

from argparse import ArgumentParser
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile
import ctypes
import os
import platform
import re
import shutil
import struct
import subprocess
import sys

if sys.version_info < (3, 11):
    sys.exit("Install Python 3.11 or newer to run this launcher.")

from configure_build import APPLICATION_ID
from windows_toolchain import (
    BuildError, Versions, android_sdk, build_environment, curl, digest, go_home,
    gradle_home, jdk_home, run,
)

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent.parent
APP_ORIGIN = "https://github.com/MetaCubeX/ClashMetaForAndroid"
MIHOMO_ORIGIN = "https://github.com/MetaCubeX/mihomo"
KERNEL_PATH = "core/src/foss/golang/clash"
APP_PATCH = TOOLS / "clashmeta-t-app.patch"
KERNEL_PATCH = TOOLS / "mihomo-tailscale-inbound.patch"
BASE_TAG = "v2.11.37"
BASE_TAG_COMMIT = "f454fa8c569ea2a2396f2fe453ac8263832001d8"
BASE_APP = "215e017ae88ac2a1edf24fdb520512c1423c89f4"
BASE_KERNEL = "0455d0d28c4526937380505153e65a843d8612e8"
VERSION_PATTERN = r"v\d+\.\d+\.\d+"


@contextmanager
def short_build_path(cache):
    import msvcrt

    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "windows-build.lock").open("a+b") as lock:
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise BuildError("Another ClashMeta-T build is using this cache. Wait for it to finish.") from error
        mounted = None
        try:
            used = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in "GHIJKLMPQRSTUVWXYZ":
                if not used & (1 << (ord(letter) - ord("A"))):
                    candidate = letter + ":"
                    run("subst.exe", candidate, cache)
                    mounted = candidate
                    yield Path(mounted + "\\")
                    return
            raise BuildError("No free drive letter for the Android toolchain's short build path.")
        finally:
            if mounted is not None:
                subprocess.run(["subst.exe", mounted, "/D"], check=False)
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def resolve_release(requested, local):
    if local:
        return BASE_TAG, BASE_APP
    if requested is None:
        latest = curl(APP_ORIGIN + "/releases/latest", "--output", os.devnull, "--write-out", "%{url_effective}")
        page = re.fullmatch(re.escape(APP_ORIGIN) + r"/releases/tag/(v\d+\.\d+\.\d+)", latest)
        if not page:
            raise BuildError(f"Official latest release did not resolve to a stable version: {latest}")
        requested = page[1]
    ref = f"refs/tags/{requested}"
    refs = dict(line.split("\t")[::-1] for line in run(
        "git", "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=30",
        "ls-remote", "--exit-code", APP_ORIGIN + ".git", ref, ref + "^{}", capture=True,
    ).splitlines())
    revision = refs.get(ref + "^{}", refs.get(ref))
    if not revision or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise BuildError(f"Cannot resolve the official tag {requested} to a Git commit.")
    if requested == BASE_TAG and revision == BASE_TAG_COMMIT:
        # This tag precedes the official version-name correction by one commit.
        revision = BASE_APP
    return requested, revision


def checkout(seed, project, remote, revision):
    if (seed / ".git").exists():
        run("git", "clone", "--local", "--no-hardlinks", "--no-checkout", seed, project)
    else:
        run("git", "init", "--quiet", project)
    found = subprocess.run(
        ["git", "cat-file", "-e", revision + "^{commit}"], cwd=project,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not found:
        run("git", "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=30",
            "fetch", "--no-tags", "--depth=1", remote + ".git", revision, cwd=project)
    run("git", "checkout", "--quiet", "--detach", revision, cwd=project)


def apply_overlay(project, patch, label):
    try:
        run("git", "apply", "--3way", patch, cwd=project)
    except subprocess.CalledProcessError as error:
        details = run("git", "status", "--short", cwd=project, capture=True)
        if details:
            print(details, file=sys.stderr)
        raise BuildError(f"{label} no longer applies cleanly. Update {patch.name} for this upstream release.") from error


def declared_kernel(project):
    entry = run("git", "ls-tree", "HEAD", KERNEL_PATH, cwd=project, capture=True)
    match = re.fullmatch(r"160000 commit ([0-9a-f]{40})\t" + re.escape(KERNEL_PATH), entry)
    if not match:
        raise BuildError(f"CMFA no longer pins the Android Mihomo submodule at {KERNEL_PATH}.")
    url = run("git", "config", "-f", ".gitmodules", "--get", "submodule.clash-foss.url", cwd=project, capture=True)
    if url.removesuffix(".git").rstrip("/") != MIHOMO_ORIGIN:
        raise BuildError(f"The Android kernel repository has changed to {url}. Review the submodule before building.")
    return match[1]


def configure_arm64(project, tag):
    gradle = project / "build.gradle.kts"
    content = gradle.read_text(encoding="utf-8")
    major, minor, patch = [int(piece) for piece in tag[1:].split(".")]
    settings = (
        (r'(?m)^(\s*versionName\s*=\s*)"[^"]+"', rf'\g<1>"{tag[1:]}"', "versionName"),
        (r'(?m)^(\s*versionCode\s*=\s*)\d+', rf'\g<1>{major}{minor:02d}{patch:03d}', "versionCode"),
        (r'(?m)^(\s*abiFilters\s*\+=\s*listOf\()[^\r\n]+\)', r'\g<1>"arm64-v8a")', "NDK ABI filters"),
        (r'(?m)^(\s*abiFilters\()[^\r\n]+\)', r'\g<1>"arm64-v8a")', "CMake ABI filters"),
    )
    for pattern, replacement, field in settings:
        content, count = re.subn(pattern, replacement, content)
        if count != 1:
            raise BuildError(f"Cannot configure {field} in the new Gradle source. Check build.gradle.kts.")
    splits = re.compile(r"(?ms)(^([ \t]*)splits\s*\{\s*abi\s*\{).*?^\2\}")
    content, count = splits.subn("", content)
    if count != 1:
        raise BuildError("The Gradle APK split configuration has changed. Review the ARM64 build settings.")
    gradle.write_text(content, encoding="utf-8")


def ensure_no_native_inbound(kernel):
    has_listener = any((kernel / path).exists() for path in ("listener/tailscale.go", "listener/inbound/tailscale.go"))
    result = subprocess.run(
        ["git", "grep", "-n", '-e', 'case "tailscale":', "--", "listener/", "config/"],
        cwd=kernel, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode not in (0, 1):
        raise BuildError("Could not inspect the official Mihomo listener parser.")
    if has_listener or result.returncode == 0:
        raise BuildError("This Mihomo revision appears to include Tailscale inbound. Check its YAML and ADB compatibility "
                         "before replacing the custom patch.")


def prepared_source(base, tag, revision):
    key = sha256(APP_PATCH.read_bytes() + KERNEL_PATCH.read_bytes() + base.drive.encode()).hexdigest()[:12]
    sources = base / "sources"
    sources.mkdir(exist_ok=True)
    project = sources / f"{tag}-{revision[:12]}-{key}"
    if project.is_dir():
        return project, declared_kernel(project)

    with TemporaryDirectory(prefix="prepare-", dir=sources) as temporary:
        pending = Path(temporary) / "project"
        checkout(REPO, pending, APP_ORIGIN, revision)
        kernel_revision = declared_kernel(pending)
        apply_overlay(pending, APP_PATCH, "Android app overlay")
        configure_arm64(pending, tag)
        kernel = pending / KERNEL_PATH
        checkout(REPO / KERNEL_PATH, kernel, MIHOMO_ORIGIN, kernel_revision)
        ensure_no_native_inbound(kernel)
        apply_overlay(kernel, KERNEL_PATCH, "Mihomo Tailscale inbound patch")
        run("git", "submodule", "init", cwd=pending)
        run("git", "update-ref", "refs/remotes/origin/CMFA-pinned", kernel_revision, cwd=kernel)
        cache_root = sources.resolve()
        if not all(path.resolve().is_relative_to(cache_root) for path in (pending, project)):
            raise BuildError("The isolated source path is outside the build cache.")
        pending.rename(project)
    return project, kernel_revision


def logged(log, args, cwd, env):
    with log.open("a", encoding="utf-8") as transcript:
        transcript.write("\n" + " ".join(map(str, args)) + "\n")
        with subprocess.Popen(
            list(map(str, args)), cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",
        ) as process:
            for line in process.stdout:
                sys.stdout.write(line)
                transcript.write(line)
            if process.wait() != 0:
                raise BuildError(f"Command failed. See the build log at {log.resolve()}.")


def build(base, project, versions):
    jdk = jdk_home(base, versions.java)
    sdk = android_sdk(base, versions)
    _, launcher = gradle_home(base, versions)
    patches = sorted((project / ".github/patch").glob("*.patch"))
    go = go_home(base, versions.go, patches)
    env = build_environment(base, jdk, go, sdk)
    (project / "local.properties").write_text(
        f"sdk.dir={sdk.as_posix()}\ncustom.application.id={APPLICATION_ID}\nremove.suffix=true\n",
        encoding="utf-8",
    )
    log = base / "windows-build.log"
    log.write_text("", encoding="utf-8")
    java = jdk / "bin/java.exe"
    print("\n[3/4] Testing the patched Mihomo kernel and compiling the Android app", flush=True)
    logged(log, [go / "bin/go.exe", "test", "-tags", "with_gvisor,cmfa", "./config", "./listener"],
           project / KERNEL_PATH, env)
    logged(log, [
        java, "-classpath", launcher, "org.gradle.launcher.GradleMain",
        "--no-daemon", "--no-watch-fs", "--console=plain", "--max-workers=4", "app:assembleAlphaRelease",
    ], project, env)
    return java, sdk / "build-tools" / versions.build_tools


def apk_signer(java, tools, apk):
    result = subprocess.run(
        list(map(str, [java, "-jar", tools / "lib/apksigner.jar", "verify", "--print-certs", apk])),
        capture_output=True, encoding="utf-8", errors="replace",
    )
    signer = re.search(r"certificate SHA-256 digest: ([0-9a-f]{64})", result.stdout)
    if result.returncode != 0 or signer is None:
        raise BuildError(f"APK signature verification failed for {apk.name}. {result.stderr.strip()}")
    return signer[1]


def publish_apk(project, tag, kernel_revision, java, tools):
    outputs = list((project / "app/build/outputs/apk/alpha/release").glob("*.apk"))
    if len(outputs) != 1:
        raise BuildError(f"Expected one ARM64 release APK, found {len(outputs)}.")
    apk = outputs[0]
    badging = run(tools / "aapt2.exe", "dump", "badging", apk, capture=True)
    package = re.search(r"(?m)^package: name='([^']+)' .*versionName='([^']+)'", badging)
    if not package or package.groups() != (APPLICATION_ID, tag[1:]):
        raise BuildError("The APK has an unexpected application ID or version.")
    if "application-label:'ClashMeta-T'" not in badging or "native-code: 'arm64-v8a'" not in badging.splitlines():
        raise BuildError("The APK has an unexpected launcher name or native ABI.")
    resources = run(tools / "aapt2.exe", "dump", "resources", apk, capture=True)
    if "Clash Meta & Tailscale" not in resources:
        raise BuildError("The full Clash Meta & Tailscale display name is missing from the APK.")
    with ZipFile(apk) as archive:
        corruption = archive.testzip()
        if corruption:
            raise BuildError(f"Corrupt APK entry: {corruption}")
        native = "lib/arm64-v8a/libclash.so"
        if native not in archive.namelist():
            raise BuildError("The APK is missing the ARM64 Mihomo library.")
        core = archive.read(native)
        if len(core) < 20 or not core.startswith(b"\x7fELF") or struct.unpack_from("<H", core, 18)[0] != 183:
            raise BuildError("The native Mihomo library is not an ARM64 ELF binary.")
        if b"duplicate Tailscale binding" not in core or b"unsupported Tailscale listener option" not in core:
            raise BuildError("The APK does not contain the tested general-purpose Tailscale listener.")

    signer = apk_signer(java, tools, apk)
    output = REPO / "dist"
    output.mkdir(exist_ok=True)
    earlier = list(output.glob("ClashMeta-T-*.apk")) + list(REPO.parent.glob("ClashMeta-T-*.apk"))
    filename = f"ClashMeta-T-{tag}-{kernel_revision[:8]}-arm64-v8a.apk"
    if earlier:
        previous = max(earlier, key=lambda item: item.stat().st_mtime_ns)
        try:
            previous_signer = apk_signer(java, tools, previous)
        except BuildError:
            previous_signer = None
        if previous_signer is None:
            print(f"WARNING: Could not compare the new signing key with {previous.name}.")
            filename = f"ClashMeta-T-{tag}-{kernel_revision[:8]}-arm64-v8a-{signer[:8]}.apk"
        elif previous_signer != signer:
            print("WARNING: This APK uses a different test signing key from your previous ClashMeta-T build.")
            filename = f"ClashMeta-T-{tag}-{kernel_revision[:8]}-arm64-v8a-{signer[:8]}.apk"
        else:
            print("Test signing key matches the previous ClashMeta-T APK.")
    final = output / filename
    partial = final.with_suffix(".apk.partial")
    shutil.copyfile(apk, partial)
    wanted = digest(apk)
    if digest(partial) != wanted:
        raise BuildError("Copying the verified APK changed its SHA-256 checksum.")
    partial.replace(final)
    print(f"\nAPK: {final}\nSHA-256: {wanted}\n")


def main():
    parser = ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--local", action="store_true", help=f"build the known {BASE_TAG} baseline")
    source.add_argument("--tag", metavar="vX.Y.Z", help="choose an official release instead of the latest")
    parser.add_argument("--check", action="store_true", help="resolve the sources and check the overlays without building")
    args = parser.parse_args()
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise BuildError("This launcher requires 64-bit x86 Windows.")
    for executable in ("git", "curl.exe"):
        if not shutil.which(executable):
            raise BuildError(f"Required command not found on PATH: {executable}")
    if args.tag and not re.fullmatch(VERSION_PATTERN, args.tag):
        parser.error("--tag expects an official stable release such as v2.11.37")
    print("[1/4] Resolving the official Clash Meta for Android release", flush=True)
    tag, revision = resolve_release(args.tag, args.local)
    cache = REPO.parent / ".clashmeta-build"
    with short_build_path(cache) as base:
        print(f"CMFA {tag} - {revision}", flush=True)
        print("\n[2/4] Checking CMFA and its declared Mihomo/Tailscale integration", flush=True)
        project, kernel = prepared_source(base, tag, revision)
        print(f"Mihomo: {kernel}" + (" (previously tested baseline)" if kernel == BASE_KERNEL else " (new revision)"))
        gomod = (project / KERNEL_PATH / "go.mod").read_text(encoding="utf-8")
        tailscale = re.search(r"(?m)^\s*(github\.com/metacubex/tailscale|tailscale\.com)\s+(\S+)", gomod)
        if not tailscale:
            raise BuildError("Cannot find the Tailscale module in the Android kernel's Go dependencies.")
        print(f"Tailscale dependency: {tailscale[1]} {tailscale[2]}")
        versions = Versions.from_app(project)
        print(f"Toolchain: JDK {versions.java}, Go {versions.go}, Gradle {versions.gradle}, "
              f"Android SDK {versions.sdk}, NDK {versions.ndk}", flush=True)
        if args.check:
            print("Source and patch checks passed. Full build and verification are performed when run without --check.")
            return
        java, tools = build(base, project, versions)
        print("\n[4/4] Verifying and exporting the signed APK", flush=True)
        publish_apk(project, tag, kernel, java, tools)


if __name__ == "__main__":
    try:
        main()
    except (BuildError, OSError, BadZipFile, subprocess.CalledProcessError) as error:
        print(f"\nBuild stopped: {error}", file=sys.stderr)
        sys.exit(1)
