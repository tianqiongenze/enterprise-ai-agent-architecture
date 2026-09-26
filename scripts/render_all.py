# -*- coding: utf-8 -*-
"""全量渲染: 42 份 PPTX → PDF → PNG(90dpi), 生成走查 manifest。"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path(r"D:/projects/企业级Agent工程架构")
RENDER = Path(r"C:/Users/Lenovo/AppData/Local/Temp/ppt_full")
SOFFICE = r"C:/Program Files/LibreOffice/program/soffice.exe"

def main():
    RENDER.mkdir(parents=True, exist_ok=True)
    decks = sorted(ROOT.glob("chapters/pptx/part*/*.pptx"))
    print("decks:", len(decks))
    manifest = []
    for i, pptx in enumerate(decks, 1):
        stem = pptx.stem
        part = pptx.parent.name
        deck_dir = RENDER / part / stem
        deck_dir.mkdir(parents=True, exist_ok=True)
        pdf = deck_dir / f"{stem}.pdf"
        if not pdf.exists():
            r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf",
                                "--outdir", str(deck_dir), str(pptx)],
                               capture_output=True, timeout=240)
            if not pdf.exists():
                print(f"[FAIL-pdf] {stem}", (r.stderr or b"")[-120:])
                continue
        r2 = subprocess.run(["pdftoppm", "-png", "-r", "90", str(pdf), str(deck_dir / "pg")],
                            capture_output=True, timeout=120)
        pages = sorted(deck_dir.glob("pg-*.png"))
        manifest.append({"deck": stem, "part": part,
                         "pages": [str(p) for p in pages]})
        print(f"[{i}/{len(decks)}] {stem} pages={len(pages)}", flush=True)
    json.dump(manifest, open(RENDER / "manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total = sum(len(m["pages"]) for m in manifest)
    print(f"=== rendered decks={len(manifest)} pages={total} ===")

if __name__ == "__main__":
    main()