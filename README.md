## Clash Meta & Tailscale

ClashMeta-T is an Android app based on [Clash Meta for Android](https://github.com/MetaCubeX/ClashMetaForAndroid) with configurable Tailscale inbound forwarding.

See the [Tailscale inbound configuration guide](docs/CM-TFA_ROADMAP.md) for TCP and UDP examples, standalone nodes, and outbound identity sharing.

### Requirement

- Android 5.0+ (minimum)
- Android 7.0+ (recommend)
- `armeabi-v7a` , `arm64-v8a`, `x86` or `x86_64` Architecture

### Build

On Windows, open [Build-ClashMeta-T.cmd](Build-ClashMeta-T.cmd) to check the latest official release and build a signed ARM64 APK. See the [Windows build guide](docs/WINDOWS_BUILD.md) for the output path, signing key, and compatibility checks.

#### Manual build

1. Update submodules

   ```bash
   git submodule update --init --recursive
   ```

2. Apply the Tailscale inbound patch to a clean checkout of the pinned Android Mihomo submodule.

   ```bash
   git -C core/src/foss/golang/clash apply ../../../../../tools/cmtfa/mihomo-tailscale-inbound.patch
   ```

3. Install **JDK 21**, **Android SDK 35**, **NDK**, **CMake**, and **Go 1.26**. The [test APK workflow](.github/workflows/cmtfa-android-test.yml) records the build toolchain and Go patches.

4. Create `local.properties` in the project root. Use the existing ClashMeta-T package ID for the standalone build.

   ```properties
   sdk.dir=/path/to/android-sdk
   custom.application.id=com.jiang831.cmtfa
   remove.suffix=true
   ```

5. For custom release signing, create `signing.properties` in the project root with

   ```properties
   keystore.path=/path/to/keystore/file
   keystore.password=<key store password>
   key.alias=<key alias>
   key.password=<key password>
   ```

6. Build

   ```bash
   ./gradlew app:assembleAlphaRelease
   ```

### Automation

The ClashMeta-T test build uses package ID `com.jiang831.cmtfa`. The action strings below are inherited from upstream.

- Toggle Clash.Meta service status
  - Send intent to activity `com.github.kr328.clash.ExternalControlActivity` with action `com.github.metacubex.clash.meta.action.TOGGLE_CLASH`
- Start Clash.Meta service
  - Send intent to activity `com.github.kr328.clash.ExternalControlActivity` with action `com.github.metacubex.clash.meta.action.START_CLASH`
- Stop Clash.Meta service
  - Send intent to activity `com.github.kr328.clash.ExternalControlActivity` with action `com.github.metacubex.clash.meta.action.STOP_CLASH`
- Import a profile
  - URL Scheme `clash://install-config?url=<encoded URI>` or `clashmeta://install-config?url=<encoded URI>`

### Contribution and Project Maintenance

#### Meta Kernel

- CMFA uses the kernel from `android-real` branch under `MetaCubeX/Clash.Meta`, which is a merge of the main `Alpha` branch and `android-open`.
  - If you want to contribute to the kernel, make PRs to `Alpha` branch of the Meta kernel repository.
  - If you want to contribute Android-specific patches to the kernel, make PRs to  `android-open` branch of the Meta kernel repository.

#### Maintenance

- When `MetaCubeX/Clash.Meta` kernel is updated to a new version, the `Update Dependencies` actions in this repo will be triggered automatically.
  - It will pull the new version of the meta kernel, update all the golang dependencies, and create a PR without manual intervention.
  - If there is any compile error in PR, you need to fix it before merging. Alternatively, you may merge the PR directly.
- Manually triggering `Build Pre-Release` actions will compile and publish a `PreRelease` version.
- Manually triggering `Build Release` actions will compile, tag and publish a `Release` version.
  - You must fill the blank `Release Tag` with the tag you want to release in the format of `v1.2.3`.
  - `versionName` and `versionCode` in `build.gradle.kts` will be automatically bumped to the tag you filled above.
