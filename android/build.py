"""Build the kiosk APK with plain Android SDK tools (no Gradle, no AndroidX).

Pipeline: aapt2 compile/link -> javac -> d8 -> zipalign -> apksigner.
Needs: build-tools and a platform under ANDROID_SDK_ROOT (default %LOCALAPPDATA%\\Android\\Sdk), a JDK on PATH.

    python android/build.py            -> android/build/eink-dashboard.apk
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(ROOT, "config.json")
CONFIG_EXAMPLE = os.path.join(ROOT, "config.example.json")
SDK = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME") \
    or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")
MIN_SDK, TARGET_SDK = "29", "34"
VERSION_NAME = "0.1"
KEYSTORE = os.path.join(HERE, "eink-debug.keystore")
KS_PASS = "android"
EXE = ".exe" if os.name == "nt" else ""
BAT = ".bat" if os.name == "nt" else ""


def newest(pattern):
    hits = sorted(glob.glob(pattern))
    if not hits:
        sys.exit(f"nothing matches {pattern}; install the Android build-tools/platform first")
    return hits[-1]


def run(cmd, **kw):
    print("  $", " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
    subprocess.run(cmd, check=True, **kw)


def dashboard_urls():
    """URL list baked into the app, from the (git-ignored) config.json so LAN addresses never land in source."""
    path = CONFIG if os.path.exists(CONFIG) else CONFIG_EXAMPLE
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    urls = cfg.get("dashboard_urls") or [f"http://localhost:{cfg.get('port', 8787)}/"]
    print(f"urls ({os.path.basename(path)}): {', '.join(urls)}")
    return urls


def write_urls_resource(urls):
    d = os.path.join(BUILD, "gen-res", "values")
    os.makedirs(d)
    path = os.path.join(d, "urls.xml")
    text = ",".join(urls).replace("&", "&amp;").replace("<", "&lt;")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
                f'    <string name="default_urls">{text}</string>\n</resources>\n')
    return path


def main():
    bt = newest(os.path.join(SDK, "build-tools", "*"))
    android_jar = newest(os.path.join(SDK, "platforms", "android-*", "android.jar"))
    aapt2 = os.path.join(bt, "aapt2" + EXE)
    d8 = os.path.join(bt, "d8" + BAT)
    zipalign = os.path.join(bt, "zipalign" + EXE)
    apksigner = os.path.join(bt, "apksigner" + BAT)
    print(f"build-tools: {bt}\nplatform:    {android_jar}")

    shutil.rmtree(BUILD, ignore_errors=True)
    for d in ("gen", "classes", "dex"):
        os.makedirs(os.path.join(BUILD, d))

    # 1. resources + manifest (static res/ plus the generated URL list)
    res_zip = os.path.join(BUILD, "res.zip")
    run([aapt2, "compile", "--dir", os.path.join(HERE, "res"), "-o", res_zip])
    urls_zip = os.path.join(BUILD, "res-urls.zip")
    run([aapt2, "compile", write_urls_resource(dashboard_urls()), "-o", urls_zip])
    base_apk = os.path.join(BUILD, "base.apk")
    run([aapt2, "link", "-o", base_apk, "-I", android_jar,
         "--manifest", os.path.join(HERE, "AndroidManifest.xml"),
         "--java", os.path.join(BUILD, "gen"),
         "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK,
         "--version-code", str(int(time.time()) // 60), "--version-name", VERSION_NAME,
         res_zip, urls_zip])

    # 2. java -> class
    sources = glob.glob(os.path.join(HERE, "src", "**", "*.java"), recursive=True) + \
        glob.glob(os.path.join(BUILD, "gen", "**", "R.java"), recursive=True)
    run(["javac", "-source", "11", "-target", "11", "-Xlint:-options", "-encoding", "UTF-8",
         "-cp", android_jar, "-d", os.path.join(BUILD, "classes")] + sources)

    # 3. class -> dex
    classes = glob.glob(os.path.join(BUILD, "classes", "**", "*.class"), recursive=True)
    run([d8, "--release", "--min-api", MIN_SDK, "--lib", android_jar, "--output", os.path.join(BUILD, "dex")] + classes)

    # 4. assemble (append dex to the aapt2 output without touching resources.arsc alignment)
    unsigned = os.path.join(BUILD, "unsigned.apk")
    shutil.copyfile(base_apk, unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(BUILD, "dex", "classes.dex"), "classes.dex")
    aligned = os.path.join(BUILD, "aligned.apk")
    run([zipalign, "-f", "-p", "4", unsigned, aligned])

    # 5. sign (self-signed key kept next to the sources so re-installs keep working)
    if not os.path.exists(KEYSTORE):
        run(["keytool", "-genkeypair", "-keystore", KEYSTORE, "-alias", "eink", "-keyalg", "RSA", "-keysize", "2048",
             "-validity", "10000", "-storepass", KS_PASS, "-keypass", KS_PASS, "-dname", "CN=eink dashboard"])
    out = os.path.join(BUILD, "eink-dashboard.apk")
    run([apksigner, "sign", "--ks", KEYSTORE, "--ks-key-alias", "eink", "--ks-pass", "pass:" + KS_PASS,
         "--key-pass", "pass:" + KS_PASS, "--out", out, aligned])
    run([apksigner, "verify", out])
    print(f"\nOK -> {out}  ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
