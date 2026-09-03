#!/usr/bin/env python3
"""Build deterministic press-kit and evidence ZIP archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


VERSION = "1.0.0"
CAMPAIGN = "article1-unified-v4-2-fb3f101b-20260903-000401"
ZIP_TIME = (2026, 9, 3, 0, 0, 0)


def files_under(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def add_tree(mapping: dict[str, Path], source: Path, destination: str) -> None:
    for path in files_under(source):
        mapping[f"{destination}/{path.relative_to(source).as_posix()}"] = path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_zip(output: Path, prefix: str, mapping: dict[str, Path], metadata: dict) -> None:
    blobs = {name: path.read_bytes() for name, path in mapping.items()}
    manifest = "".join(f"{sha256(blobs[name])}  {name}\n" for name in sorted(blobs)).encode()
    release_manifest = json.dumps(metadata | {"files": len(blobs)}, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    generated = {"SHA256SUMS": manifest, "RELEASE_MANIFEST.json": release_manifest}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted((blobs | generated).items()):
            info = zipfile.ZipInfo(f"{prefix}/{name}", ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pdf-en", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output/releases"))
    args = parser.parse_args()
    root = args.root.resolve()
    pdf = args.pdf.resolve()
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    pdf_en = args.pdf_en.resolve() if args.pdf_en else None
    if pdf_en is not None and not pdf_en.is_file():
        raise FileNotFoundError(pdf_en)

    press = root / "press"
    raw = press / "results" / "raw"
    common = {
        "VERSION": press / "VERSION",
        "RELEASE_NOTES.md": press / "RELEASE_NOTES.md",
        "LICENSE": press / "LICENSE",
        "THIRD_PARTY_NOTICES.md": press / "THIRD_PARTY_NOTICES.md",
    }
    main_files = dict(common)
    main_files.update({
        "CITATION.cff": root / "CITATION.cff",
        "README.md": press / "README.md",
        "article/beyond-throughput-tomcat-lifecycle-v4-2.md": press / "article" / "beyond-throughput-tomcat-lifecycle-v4-2.md",
        "article/beyond-throughput-tomcat-lifecycle-v4-2-en.md": press / "article" / "beyond-throughput-tomcat-lifecycle-v4-2-en.md",
        "article/beyond-throughput-tomcat-lifecycle.md": press / "article" / "beyond-throughput-tomcat-lifecycle.md",
        "article/beyond-throughput-tomcat-lifecycle.pdf": pdf,
        "article/protocollo-campagna-v4-2.md": press / "article" / "protocollo-campagna-v4-2.md",
        "results/Beyond_Throughput_Lifecycle_v4_2_Results.xlsx": press / "results" / "Beyond_Throughput_Lifecycle_v4_2_Results.xlsx",
        "results/README.md": press / "results" / "README.md",
        "results/SOURCE_SHA256SUMS": press / "results" / "SHA256SUMS",
        "results/summary.csv": raw / f"{CAMPAIGN}-summary.csv",
        "results/forks.csv": raw / f"{CAMPAIGN}-forks.csv",
        "results/lifecycle-summary.csv": raw / f"{CAMPAIGN}-lifecycle-summary.csv",
        "run-benchmark.ps1": press / "run-benchmark.ps1",
    })
    if pdf_en is not None:
        main_files["article/beyond-throughput-tomcat-lifecycle-en.pdf"] = pdf_en
    add_tree(main_files, press / "article" / "figures", "article/figures")
    add_tree(main_files, press / "article" / "fonts", "article/fonts")
    add_tree(main_files, press / "benchmark", "benchmark")
    for script in (
        "run_benchmark.py", "validate_campaign_v4.py", "extract_paper_v4_2.py",
        "fill_paper_v4_2.py", "generate_paper_figures.py", "generate_v4_2_workbook.mjs",
        "render_paper_pdf.mjs", "build_press_release.py",
        "test_run_benchmark.py", "test_validate_campaign_v4.py",
        "test_extract_paper_v4_2.py", "test_fill_paper_v4_2.py",
    ):
        main_files[f"scripts/{script}"] = root / "scripts" / script

    evidence_files = dict(common)
    evidence_files.update({
        "README.md": press / "results" / "README.md",
        "SOURCE_SHA256SUMS": press / "results" / "SHA256SUMS",
    })
    for suffix in (
        "results.json", "analysis.json", "summary.csv", "forks.csv",
        "lifecycle-summary.csv", "lifecycle-forks.csv", "observations.csv",
        "paper-values.json", "build.log", "diagnostics.zip", "raw.partial.json",
    ):
        evidence_files[f"evidence/{CAMPAIGN}-{suffix}"] = raw / f"{CAMPAIGN}-{suffix}"

    missing = [str(path) for path in (*main_files.values(), *evidence_files.values()) if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing release inputs: " + ", ".join(missing))
    forbidden = ("v4-1", "pilot", "smoke", "revisione-avversariale", "protocollo-campagna-v4.md")
    for name in (*main_files, *evidence_files):
        if any(token in name.lower() for token in forbidden):
            raise ValueError(f"excluded pre-v4.2/internal artifact selected: {name}")

    metadata = {"release": VERSION, "protocol": "4.2", "campaign": CAMPAIGN}
    output_dir = args.output_dir.resolve()
    build_zip(output_dir / f"beyond-throughput-press-{VERSION}.zip", f"beyond-throughput-press-{VERSION}", main_files, metadata | {"package": "press"})
    build_zip(output_dir / f"beyond-throughput-evidence-{VERSION}.zip", f"beyond-throughput-evidence-{VERSION}", evidence_files, metadata | {"package": "evidence"})
    print(f"Built release archives in {output_dir}")


if __name__ == "__main__":
    main()
