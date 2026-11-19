"""Install the Windows build tools into a reusable, private build directory."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import file_digest, sha256
from pathlib import Path
from shutil import copyfileobj
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from zipfile import ZipFile


ANDROID_REPOSITORY = "https://dl.google.com/android/repository/"
GO_RELEASE = "https://github.com/MetaCubeX/go/releases/"
GO_126_WINDOWS_SHA256 = "0c864c2d6e39b6fab62dc3a491a2d43d3c0d3e9ae70117e04148601159820237"


class BuildError(RuntimeError):
    pass


def run(*args, cwd=None, env=None, capture=False):
    result = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, env=env, check=True,
        stdout=subprocess.PIPE if capture else None,
        encoding="utf-8", errors="replace",
    )
    return result.stdout.strip() if capture else None


def curl(url, *args, timeout=90):
    return run("curl.exe", "-fsSL", "--retry", "2", "--connect-timeout", "15",
               "--max-time", timeout, *args, url, capture=True)


def digest(path, algorithm="sha256"):
    with path.open("rb") as contents:
        return file_digest(contents, algorithm).hexdigest()


def download(directory, url, name=None, expected=None):
    name = name or url.rsplit("/", 1)[-1]
    path = directory / name
    algorithm = "sha1" if expected and len(expected) == 40 else "sha256"
    if path.is_file() and path.stat().st_size and (expected is None or digest(path, algorithm) == expected):
        return path
    partial = path.with_suffix(path.suffix + ".partial")
    print(f"Downloading {name} ...", flush=True)
    curl(url, "--output", partial, timeout=900)
    if expected and digest(partial, algorithm) != expected:
        raise BuildError(f"Checksum mismatch for {name}. Check its official download metadata.")
    partial.replace(path)
    return path


def unpack(path, target, strip_root=True):
    finished = target / ".clashmeta-extracted"
    if finished.is_file():
        return
    print(f"Extracting {path.name} ...", flush=True)
    target.mkdir(parents=True, exist_ok=True)
    with ZipFile(path) as archive:
        entries = archive.infolist()
        roots = {entry.filename.split("/", 1)[0] for entry in entries}
        if strip_root and len(roots) != 1:
            raise BuildError(f"Unexpected top-level structure in {path.name}")
        for entry in entries:
            name = entry.filename.partition("/")[2] if strip_root else entry.filename
            if not name:
                continue
            relative = Path(name)
            if relative.anchor or ".." in relative.parts or ":" in name:
                raise BuildError(f"Unsafe archive entry in {path.name}: {name}")
            output = target / relative
            if entry.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, output.open("wb") as destination:
                    copyfileobj(source, destination, 1024 * 1024)
    finished.touch()


@dataclass(frozen=True)
class Versions:
    java: str
    go: str
    gradle_url: str
    sdk: str
    build_tools: str
    ndk: str
    cmake: str

    @property
    def gradle(self):
        return re.search(r"/gradle-([\d.]+)-(?:bin|all)\.zip$", self.gradle_url)[1]

    @classmethod
    def from_app(cls, project):
        gradle = (project / "build.gradle.kts").read_text(encoding="utf-8")
        core = (project / "core/build.gradle.kts").read_text(encoding="utf-8")
        wrapper = (project / "gradle/wrapper/gradle-wrapper.properties").read_text(encoding="utf-8")
        release = (project / ".github/workflows/build-release.yaml").read_text(encoding="utf-8")

        def read(pattern, text, label, default=None):
            values = set(re.findall(pattern, text, flags=re.MULTILINE))
            if not values and default is not None:
                return default
            if len(values) != 1:
                raise BuildError(f"Cannot determine {label} from this release's build files.")
            return values.pop()

        sdk = read(r"^\s*targetSdk\s*=\s*(\d+)", gradle, "Android SDK version")
        gradle_url = read(
            r"^distributionUrl=(https://services\.gradle\.org/distributions/gradle-[\d.]+-(?:bin|all)\.zip)$",
            wrapper.replace(r"\:", ":"), "Gradle distribution URL",
        )
        cmake_block = re.search(r'(?ms)^([ \t]*)cmake\s*\{\s*\n(.*?)^\1\}', core)
        return cls(
            java=read(r'^\s*java-version:\s*["\']?(\d+)["\']?\s*$', release, "JDK version"),
            go=read(r'^\s*go-version:\s*["\']?(1\.\d+)["\']?\s*$', release, "MetaCubeX Go version"),
            gradle_url=gradle_url, sdk=sdk,
            build_tools=read(r'buildToolsVersion\s*=\s*"([\d.]+)"', gradle, "Build Tools", f"{sdk}.0.0"),
            ndk=read(r'ndkVersion\s*=\s*"([\d.]+)"', gradle, "NDK version"),
            cmake=read(r'(?m)^\s*version\s*=\s*"([\d.]+)"', cmake_block[2] if cmake_block else "",
                       "CMake version", "3.22.1"),
        )


def android_sdk(base, versions):
    sdk = base / "sdk"
    packages = {
        f"platforms;android-{versions.sdk}": (f"platforms/android-{versions.sdk}", "android.jar", True),
        f"build-tools;{versions.build_tools}": (f"build-tools/{versions.build_tools}", "aapt2.exe", True),
        f"ndk;{versions.ndk}": (f"ndk/{versions.ndk}", "source.properties", True),
        f"cmake;{versions.cmake}": (f"cmake/{versions.cmake}", "bin/cmake.exe", False),
        "platform-tools": ("platform-tools", "adb.exe", True),
    }
    missing = {name: info for name, info in packages.items()
               if not (sdk / info[0] / ".clashmeta-extracted").is_file() or not (sdk / info[0] / info[1]).is_file()}
    if not missing:
        return sdk
    metadata = ET.fromstring(curl(ANDROID_REPOSITORY + "repository2-1.xml"))
    official = {pkg.attrib["path"]: pkg for pkg in metadata.findall("remotePackage")}

    def install(item):
        name, (destination, marker, strip_root) = item
        package = official.get(name)
        if package is None:
            raise BuildError(f"Android SDK package {name} is missing from Google's release manifest.")
        for candidate in package.findall("archives/archive"):
            if candidate.findtext("host-os") not in (None, "windows"):
                continue
            url = candidate.findtext("complete/url")
            checksum = candidate.findtext("complete/checksum")
            if url and checksum:
                target = sdk / destination
                (target / ".clashmeta-extracted").unlink(missing_ok=True)
                unpack(download(base, ANDROID_REPOSITORY + url, expected=checksum), target, strip_root)
                if not (target / marker).is_file():
                    raise BuildError(f"{name} did not contain {marker}")
                return
        raise BuildError(f"No Windows archive with a checksum found for {name}.")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(install, missing.items()))
    return sdk


def jdk_home(base, major):
    existing = base / "jdk"
    release = existing / "release"
    if release.is_file() and re.search(rf'^JAVA_VERSION="{major}\.', release.read_text(), re.MULTILINE):
        return existing
    target = base / f"jdk-{major}"
    if not (target / ".clashmeta-extracted").is_file():
        archive = download(base, f"https://aka.ms/download-jdk/microsoft-jdk-{major}-windows-x64.zip",
                           f"jdk-{major}.zip")
        unpack(archive, target)
    return target


def gradle_home(base, versions):
    launcher = f"lib/gradle-gradle-cli-main-{versions.gradle}.jar"
    existing = base / "gradle"
    if (existing / launcher).is_file():
        return existing, existing / launcher
    target = base / f"gradle-{versions.gradle}"
    if not (target / ".clashmeta-extracted").is_file():
        expected = curl(versions.gradle_url + ".sha256").split()[0]
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise BuildError("Cannot read the official Gradle SHA-256 checksum.")
        unpack(download(base, versions.gradle_url, expected=expected.lower()), target)
    candidates = [target / launcher, target / f"lib/gradle-launcher-{versions.gradle}.jar"]
    for entry in candidates:
        if entry.is_file():
            return target, entry
    raise BuildError(f"Cannot locate the Gradle launcher in {target}.")


def go_home(base, version, patches):
    patch_input = b"".join(path.read_bytes() for path in patches)
    key = sha256(patch_input).hexdigest()[:10]
    target = base / f"go-{version}-{key}"
    if (target / ".clashmeta-patched").is_file():
        return target
    if (base / "go" / ".clashmeta-patched").is_file() and version == "1.26":
        existing = base / "go"
        if all(patch_applies(existing, patch, reverse=True) for patch in patches):
            return existing
    unpack(go_archive(base, version), target)
    for patch in patches:
        if not patch_applies(target, patch, reverse=True):
            normalized = normalize_patch(target, patch)
            run("git", "apply", normalized, cwd=target)
    (target / ".clashmeta-patched").touch()
    return target


def go_archive(base, version):
    filename = f"go{version}.windows-amd64.zip"
    archive = base / filename
    if version == "1.26" and archive.is_file() and digest(archive) == GO_126_WINDOWS_SHA256:
        return archive
    assets = curl(GO_RELEASE + "expanded_assets/build")
    link = re.search(rf'href="[^"]*/{re.escape(filename)}"', assets)
    checksum = re.search(r"sha256:([0-9a-f]{64})", assets[link.end():].split("</li>", 1)[0]) if link else None
    if not checksum:
        raise BuildError(f"No checked MetaCubeX Windows toolchain archive found for Go {version}.")
    return download(base, GO_RELEASE + "download/build/" + filename, expected=checksum[1])


def normalize_patch(directory, patch):
    normalized = directory / (".build-" + patch.name)
    normalized.write_bytes(patch.read_bytes().replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n")
    return normalized


def patch_applies(directory, patch, *, reverse=False):
    args = ["git", "apply", "--check", str(normalize_patch(directory, patch))]
    if reverse:
        args.insert(2, "--reverse")
    return subprocess.run(args, cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def build_environment(base, jdk, go, sdk):
    env = {name: value for name, value in os.environ.items()
           if not any(marker in name.upper() for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))}
    env.update({
        "PATH": os.pathsep.join([str(jdk / "bin"), str(go / "bin"), env["PATH"]]),
        "JAVA_HOME": str(jdk),
        "ANDROID_HOME": str(sdk),
        "ANDROID_SDK_ROOT": str(sdk),
        "ANDROID_USER_HOME": str(base / "android-user"),
        "GRADLE_USER_HOME": str(base / "gradle-cache"),
        "GOROOT": str(go),
        "GOTOOLCHAIN": "local",
        "GOMODCACHE": str(base / "go-mod-cache"),
        "GOCACHE": str(base / "go-build-cache"),
        "TEMP": str(base / "tmp"),
        "TMP": str(base / "tmp"),
    })
    for name in ("android-user", "tmp"):
        (base / name).mkdir(exist_ok=True)
    env.setdefault("GOPROXY", "https://proxy.golang.org,direct")
    return env
