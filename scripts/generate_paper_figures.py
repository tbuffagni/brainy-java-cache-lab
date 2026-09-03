#!/usr/bin/env python3
"""Generate the three publication figures from the accepted v4.2 dataset."""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


CAMPAIGN = "article1-unified-v4-2-fb3f101b-20260903-000401"
PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4")
RATIO_PROVIDERS = ("caffeine", "ehcache", "cache2k")
LABEL = {
    "caffeine": "Caffeine",
    "ehcache": "Ehcache",
    "cache2k": "cache2k",
    "jcs4": "JCS 4",
    "jcs321": "JCS 3.2.1",
}
PHASE_LABEL = {"initial": "Deploy iniziale", "redeploy": "Dopo il redeploy"}
COLORS = {"initial": "#2166AC", "redeploy": "#B2182B", "jcs321": "#B2182B", "jcs4": "#2166AC"}
LANGUAGE = "it"


def tr(italian: str, english: str) -> str:
    return english if LANGUAGE == "en" else italian


def font_data_uri(name: str) -> str:
    candidates = (Path("press/article/fonts"), Path("article/fonts"))
    font_dir = next((candidate for candidate in candidates if candidate.is_dir()), None)
    if font_dir is None:
        raise FileNotFoundError("Libertinus font directory not found")
    data = base64.b64encode((font_dir / name).read_bytes()).decode("ascii")
    return f"data:font/woff2;base64,{data}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def it(value: float, digits: int = 2) -> str:
    rendered = f"{value:.{digits}f}"
    return rendered if LANGUAGE == "en" else rendered.replace(".", ",")


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def svg_start(title: str, description: str, width: int = 1000, height: int = 620) -> list[str]:
    regular = font_data_uri("LibertinusSans-Regular.woff2")
    bold = font_data_uri("LibertinusSans-Bold.woff2")
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{esc(title)}</title>",
        f"<desc id=\"desc\">{esc(description)}</desc>",
        f"<style>@font-face{{font-family:'Libertinus Sans';src:url('{regular}') format('woff2');font-weight:400}}@font-face{{font-family:'Libertinus Sans';src:url('{bold}') format('woff2');font-weight:700}}text{{font-family:'Libertinus Sans',sans-serif;fill:#202124}} .title{{font-size:22px;font-weight:700}}.subtitle{{font-size:13px;fill:#555}}.axis{{font-size:12px}}.label{{font-size:13px}}.value{{font-size:12px;font-weight:700}}.grid{{stroke:#d8dde3;stroke-width:1}}.frame{{fill:#fff;stroke:#8c939b;stroke-width:1}}.median{{stroke-width:4}}.point{{stroke:#fff;stroke-width:1}}</style>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="70" y="36" class="title">{esc(title)}</text>',
        f'<text x="70" y="58" class="subtitle">{esc(description)}</text>',
    ]


def write_svg(path: Path, parts: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts.append("</svg>")
    content = "\n".join(parts) + "\n"
    if re.search(r'(?:x|y|x1|x2|y1|y2|cx|cy|r|width|height|points)="[^"]*(?:nan|[+-]?inf)', content, re.IGNORECASE):
        raise ValueError(f"non-finite coordinate in {path}")
    path.write_text(content, encoding="utf-8", newline="\n")


def marker(parts: list[str], x: float, y: float, phase: str, radius: float = 5) -> None:
    color = COLORS[phase]
    if phase == "initial":
        parts.append(f'<circle class="point" cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{color}"/>')
    else:
        d = radius * 1.25
        points = f"{x:.2f},{y-d:.2f} {x+d:.2f},{y:.2f} {x:.2f},{y+d:.2f} {x-d:.2f},{y:.2f}"
        parts.append(f'<polygon class="point" points="{points}" fill="{color}"/>')


def legend(parts: list[str], x: int = 690, y: int = 34) -> None:
    marker(parts, x, y, "initial", 5)
    parts.append(f'<text x="{x+12}" y="{y+4}" class="label">{tr("Deploy iniziale", "Initial deployment")}</text>')
    marker(parts, x + 145, y, "redeploy", 5)
    parts.append(f'<text x="{x+157}" y="{y+4}" class="label">{tr("Dopo il redeploy", "After redeployment")}</text>')


def generate_throughput(rows: list[dict[str, str]], output: Path) -> None:
    selected = [r for r in rows if r["analysisSet"] == "primary-all-cycles" and r["provider"] in PROVIDERS and r["includedInPerformanceSummary"] == "True"]
    groups: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for row in selected:
        groups[(row["provider"], row["phase"])].append((int(row["fork"]), float(row["comparisonMedian_operationsPerSecond"]) / 1_000_000))
    if set(groups) != {(p, ph) for p in PROVIDERS for ph in PHASE_LABEL} or any(len(v) != 6 for v in groups.values()):
        raise ValueError("throughput figure requires 6 accepted JVMs for every provider and phase")

    left, right, top, bottom, width, height = 86, 30, 84, 92, 1000, 620
    plot_w, plot_h = width - left - right, height - top - bottom
    ymin, ymax = 0.7, 40.0
    ymap = lambda v: top + (math.log10(ymax) - math.log10(v)) / (math.log10(ymax) - math.log10(ymin)) * plot_h
    xstep = plot_w / len(PROVIDERS)
    xcenter = lambda i: left + xstep * (i + 0.5)
    parts = svg_start(tr("Throughput per processo Tomcat", "Throughput per Tomcat process"), tr("Sei JVM indipendenti per provider e fase; asse verticale logaritmico", "Six independent JVMs per provider and phase; logarithmic vertical axis"))
    legend(parts)
    parts.append(f'<rect class="frame" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}"/>')
    for tick in (1, 2, 5, 10, 20, 40):
        y = ymap(tick)
        parts.append(f'<line class="grid" x1="{left}" x2="{left+plot_w}" y1="{y:.2f}" y2="{y:.2f}"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" class="axis">{tick}</text>')
    parts.append(f'<text transform="translate(24 {top+plot_h/2}) rotate(-90)" text-anchor="middle" class="label">{tr("Milioni di operazioni al secondo (Mops/s, scala log)", "Millions of operations per second (Mops/s, log scale)")}</text>')
    offsets = {"initial": -0.17 * xstep, "redeploy": 0.17 * xstep}
    for index, provider in enumerate(PROVIDERS):
        parts.append(f'<text x="{xcenter(index):.2f}" y="{top+plot_h+32}" text-anchor="middle" class="label">{LABEL[provider]}</text>')
        for phase in PHASE_LABEL:
            values = [v for _, v in sorted(groups[(provider, phase)])]
            base_x = xcenter(index) + offsets[phase]
            q1, med, q3 = quantile(values, .25), statistics.median(values), quantile(values, .75)
            parts.append(f'<line x1="{base_x:.2f}" x2="{base_x:.2f}" y1="{ymap(q1):.2f}" y2="{ymap(q3):.2f}" stroke="{COLORS[phase]}" stroke-width="3"/>')
            parts.append(f'<line class="median" x1="{base_x-14:.2f}" x2="{base_x+14:.2f}" y1="{ymap(med):.2f}" y2="{ymap(med):.2f}" stroke="{COLORS[phase]}"/>')
            for fork, value in sorted(groups[(provider, phase)]):
                marker(parts, base_x + (fork - 3.5) * 3.2, ymap(value), phase, 4.5)
            parts.append(f'<text x="{base_x:.2f}" y="{ymap(med)-12:.2f}" text-anchor="middle" class="value">{it(med,3)}</text>')
    parts.append(f'<text x="{left+plot_w/2}" y="{height-20}" text-anchor="middle" class="subtitle">{tr("Punti: mediane dei cinque cicli per JVM; segmento spesso: mediana fra JVM; linea sottile: Q1–Q3.", "Points: five-cycle medians per JVM; thick segment: median across JVMs; thin line: Q1–Q3.")}</text>')
    write_svg(output, parts)


def generate_ratios(analysis: dict, output: Path) -> None:
    rows = [r for r in analysis["pairedRatios"] if r["analysisSet"] == "primary-all-cycles" and r["provider"] in RATIO_PROVIDERS]
    groups = {(r["provider"], r["phase"]): r for r in rows}
    if set(groups) != {(p, ph) for p in RATIO_PROVIDERS for ph in PHASE_LABEL} or any(len(r["valuesByBlock"]) != 6 for r in groups.values()):
        raise ValueError("ratio figure requires 6 Williams blocks for every provider and phase")

    left, right, top, bottom, width, height = 86, 30, 84, 92, 1000, 620
    plot_w, plot_h = width - left - right, height - top - bottom
    ymin, ymax = 0.0, 40.0
    ymap = lambda v: top + (ymax - v) / (ymax - ymin) * plot_h
    xstep = plot_w / len(RATIO_PROVIDERS)
    xcenter = lambda i: left + xstep * (i + 0.5)
    parts = svg_start(tr("Accelerazione rispetto a JCS 4", "Speedup relative to JCS 4"), tr("Rapporti calcolati entro lo stesso blocco Williams e la stessa fase", "Ratios computed within the same Williams block and phase"))
    legend(parts)
    parts.append(f'<rect class="frame" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}"/>')
    for tick in range(0, 41, 5):
        y = ymap(tick)
        parts.append(f'<line class="grid" x1="{left}" x2="{left+plot_w}" y1="{y:.2f}" y2="{y:.2f}"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" class="axis">{tick}×</text>')
    for reference, label in ((1, tr("parità 1×", "parity 1×")), (10, tr("ordine di grandezza 10×", "one order of magnitude 10×"))):
        y = ymap(reference)
        parts.append(f'<line x1="{left}" x2="{left+plot_w}" y1="{y:.2f}" y2="{y:.2f}" stroke="#555" stroke-width="1.5" stroke-dasharray="6 5"/>')
        parts.append(f'<text x="{left+8}" y="{y-6:.2f}" class="subtitle">{label}</text>')
    parts.append(f'<text transform="translate(24 {top+plot_h/2}) rotate(-90)" text-anchor="middle" class="label">{tr("Throughput del provider / throughput JCS 4", "Provider throughput / JCS 4 throughput")}</text>')
    offsets = {"initial": -0.15 * xstep, "redeploy": 0.15 * xstep}
    for index, provider in enumerate(RATIO_PROVIDERS):
        parts.append(f'<text x="{xcenter(index):.2f}" y="{top+plot_h+32}" text-anchor="middle" class="label">{LABEL[provider]}</text>')
        for phase in PHASE_LABEL:
            row = groups[(provider, phase)]
            values = [(int(v["block"]), float(v["ratioToJcs4"])) for v in row["valuesByBlock"]]
            base_x = xcenter(index) + offsets[phase]
            q1, med, q3 = float(row["ratioToJcs4FirstQuartile"]), float(row["ratioToJcs4Median"]), float(row["ratioToJcs4ThirdQuartile"])
            parts.append(f'<line x1="{base_x:.2f}" x2="{base_x:.2f}" y1="{ymap(q1):.2f}" y2="{ymap(q3):.2f}" stroke="{COLORS[phase]}" stroke-width="3"/>')
            parts.append(f'<line class="median" x1="{base_x-16:.2f}" x2="{base_x+16:.2f}" y1="{ymap(med):.2f}" y2="{ymap(med):.2f}" stroke="{COLORS[phase]}"/>')
            for block, value in values:
                marker(parts, base_x + (block - 3.5) * 3.5, ymap(value), phase, 4.5)
            parts.append(f'<text x="{base_x:.2f}" y="{ymap(med)-12:.2f}" text-anchor="middle" class="value">{it(med)}×</text>')
    parts.append(f'<text x="{left+plot_w/2}" y="{height-20}" text-anchor="middle" class="subtitle">{tr("Punti: sei blocchi Williams; segmento spesso: mediana; linea sottile: Q1–Q3.", "Points: six Williams blocks; thick segment: median; thin line: Q1–Q3.")}</text>')
    write_svg(output, parts)


def generate_lifecycle(rows: list[dict[str, str]], output: Path) -> None:
    groups: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for row in rows:
        if row["provider"] not in ("jcs321", "jcs4") or row["blockValid"] != "True":
            continue
        phase_index = 0 if row["phase"] == "initial" else 1
        undeploy = (int(row["cycle"]) - 1) * 2 + phase_index + 1
        groups[(row["provider"], int(row["fork"]))].append((undeploy, int(row["finalJcsThreadSignatureCount"])))
    if set(groups) != {(p, f) for p in ("jcs321", "jcs4") for f in range(1, 7)} or any(len(v) != 10 for v in groups.values()):
        raise ValueError("lifecycle figure requires 10 post-undeploy observations in 6 JVMs per JCS line")

    left, right, top, bottom, width, height = 86, 110, 84, 92, 1000, 620
    plot_w, plot_h = width - left - right, height - top - bottom
    xmap = lambda x: left + (x - 1) / 9 * plot_w
    ymap = lambda y: top + (10.5 - y) / 10.5 * plot_h
    parts = svg_start(tr("Worker JCS ancora visibili dopo ogni undeploy", "JCS workers still visible after each undeployment"), tr("Conteggio nel dump finale; sei JVM indipendenti per ciascuna versione", "Count in the final dump; six independent JVMs for each version"))
    parts.append(f'<rect class="frame" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}"/>')
    for tick in range(0, 11, 2):
        y = ymap(tick)
        parts.append(f'<line class="grid" x1="{left}" x2="{left+plot_w}" y1="{y:.2f}" y2="{y:.2f}"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" class="axis">{tick}</text>')
    for tick in range(1, 11):
        x = xmap(tick)
        parts.append(f'<text x="{x:.2f}" y="{top+plot_h+25}" text-anchor="middle" class="axis">{tick}</text>')
    parts.append(f'<text transform="translate(24 {top+plot_h/2}) rotate(-90)" text-anchor="middle" class="label">{tr("Firme di worker JCS nel dump finale", "JCS worker signatures in the final dump")}</text>')
    parts.append(f'<text x="{left+plot_w/2}" y="{height-46}" text-anchor="middle" class="label">{tr("Numero progressivo dell’undeploy nella stessa JVM", "Sequential undeployment number in the same JVM")}</text>')
    for provider in ("jcs321", "jcs4"):
        color = COLORS[provider]
        dash = "" if provider == "jcs321" else ' stroke-dasharray="8 5"'
        for fork in range(1, 7):
            values = sorted(groups[(provider, fork)])
            points = " ".join(f"{xmap(x):.2f},{ymap(y):.2f}" for x, y in values)
            parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.5" opacity="0.28"{dash}/>')
        medians = []
        for undeploy in range(1, 11):
            medians.append((undeploy, statistics.median(dict(groups[(provider, fork)])[undeploy] for fork in range(1, 7))))
        points = " ".join(f"{xmap(x):.2f},{ymap(y):.2f}" for x, y in medians)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="4"{dash}/>')
        for x, y in medians:
            parts.append(f'<circle cx="{xmap(x):.2f}" cy="{ymap(y):.2f}" r="4" fill="#fff" stroke="{color}" stroke-width="2"/>')
    parts.append(f'<text x="{xmap(10)+10:.2f}" y="{ymap(10)+4:.2f}" class="value" fill="{COLORS["jcs321"]}">JCS 3.2.1: 10</text>')
    parts.append(f'<text x="{xmap(10)+10:.2f}" y="{ymap(0)+4:.2f}" class="value" fill="{COLORS["jcs4"]}">JCS 4: 0</text>')
    parts.append(f'<text x="{left+plot_w/2}" y="{height-20}" text-anchor="middle" class="subtitle">{tr("Le sei traiettorie coincidono in entrambe le versioni; la linea spessa mostra la mediana.", "The six trajectories coincide for both versions; the thick line shows the median.")}</text>')
    write_svg(output, parts)


def main() -> None:
    global LANGUAGE
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("press/results/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("press/article/figures"))
    parser.add_argument("--language", choices=("it", "en"), default="it")
    args = parser.parse_args()
    LANGUAGE = args.language
    analysis_path = args.raw_dir / f"{CAMPAIGN}-analysis.json"
    forks_path = args.raw_dir / f"{CAMPAIGN}-forks.csv"
    observations_path = args.raw_dir / f"{CAMPAIGN}-observations.csv"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
    if analysis.get("protocolVersion") != "4.2" or analysis.get("schemaVersion") != 4:
        raise ValueError("figures require the accepted protocol/schema v4.2 analysis")
    generate_throughput(read_csv(forks_path), args.output_dir / "figure-1-throughput.svg")
    generate_ratios(analysis, args.output_dir / "figure-2-speedup-vs-jcs4.svg")
    generate_lifecycle(read_csv(observations_path), args.output_dir / "figure-3-jcs-worker-lifecycle.svg")
    print(f"Generated 3 figures in {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
