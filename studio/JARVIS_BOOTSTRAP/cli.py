#!/usr/bin/env python3
"""
JARVIS_BOOTSTRAP — arquitetura para provisionar automaticamente uma GPU
cloud descartável com um engine, no futuro.

Uso (arquitetura, NÃO EXECUTA downloads/instalações reais ainda):

    python cli.py --engine ltx
    python cli.py --engine wan

Isto lê manifests/<engine>.example.json e mostra o plano de passos que
SERIA executado por um CloudProvider (ver backend/app/engines/cloud/).
Modular por desenho: cada motor tem o seu próprio manifest; adicionar um
motor novo é criar manifests/<nome>.json, nada mais.
"""
import argparse
import json
import sys
from pathlib import Path

MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"


def load_manifest(engine: str) -> dict:
    path = MANIFESTS_DIR / f"{engine}.example.json"
    if not path.exists():
        available = [p.stem.replace(".example", "") for p in MANIFESTS_DIR.glob("*.json")]
        print(f"[erro] Não existe manifest para '{engine}'. Disponíveis: {available}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def print_plan(manifest: dict):
    print(f"Engine: {manifest['engine']}  (manifest v{manifest.get('version', '?')})")
    print("Plano (NADA é executado — isto é só a arquitetura):")
    for i, step in enumerate(manifest.get("steps", []), 1):
        print(f"  {i}. [{step['type']}] {step['id']}")
    print()
    print("Para ligar isto a uma GPU real no futuro: implementar um CloudProvider")
    print("(backend/app/engines/cloud/providers.py) e passar este manifest ao seu deploy().")


def main():
    parser = argparse.ArgumentParser(description="JARVIS Bootstrap — arquitetura de provisionamento (manifest-based)")
    parser.add_argument("--engine", required=True, help="Nome do engine (ex.: ltx, wan)")
    args = parser.parse_args()

    manifest = load_manifest(args.engine)
    print_plan(manifest)


if __name__ == "__main__":
    main()
