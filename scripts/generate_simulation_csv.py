#!/usr/bin/env python3
"""
Simulation Batch Generator
=======================================
Runs an ASA simulation batch using asapy + asaclient and saves the results
as a CSV file ready to be processed by the distributed cluster pipeline.

This script is executed as a subprocess by the AeroSOuDA CLI (cli.py) when
the user selects "Gerar novo CSV via simulação ASA".  It is designed to be
run with the Python interpreter that has asapy/asaclient installed (typically
the `asapy` conda environment).

Usage (direct):
    python generate_simulation_csv.py <json_path> <output_dir> [--server URL]

The JSON scenario file must be a valid ASA Webstation export (e.g.
quickreaction.json).

After a successful run the last line of stdout is:
    OUTPUT_CSV:<absolute_path_to_csv>
which is parsed by cli.py to locate the generated file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hr(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _ask(prompt: str, default: str = "") -> str:
    if default:
        answer = input(f"  {prompt} [{default}]: ").strip()
        return answer if answer else default
    return input(f"  {prompt}: ").strip()


def _ask_float(prompt: str, default: float) -> float:
    while True:
        raw = _ask(prompt, str(default))
        try:
            return float(raw)
        except ValueError:
            print("  Valor inválido. Digite um número.")


def _ask_int(prompt: str, default: int) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            print("  Valor inválido. Digite um número inteiro.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera CSV de resultados executando um batch de simulações ASA."
    )
    parser.add_argument("json_path", help="Caminho para o arquivo JSON do cenário ASA")
    parser.add_argument("output_dir", help="Diretório onde o CSV será salvo")
    parser.add_argument(
        "--server",
        default="https://service.asa.dcta.mil.br",
        help="URL do servidor ASA",
    )
    args = parser.parse_args()

    json_path = Path(args.json_path).resolve()
    output_dir = Path(args.output_dir).resolve()
    server_url = args.server

    # ── Verify dependencies ─────────────────────────────────────────────────
    try:
        import asapy
        import asaclient
        import pandas as pd
    except ImportError as exc:
        print(f"\nERRO: dependência não encontrada — {exc}", file=sys.stderr)
        print(
            "Ative o ambiente conda com asapy/asa-client:\n"
            "  conda activate asapy\n"
            "e tente novamente.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not json_path.exists():
        print(f"\nERRO: arquivo JSON não encontrado: {json_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    sim_name = json_path.stem
    output_csv = output_dir / f"results_{sim_name}.csv"

    _hr("=")
    print("  AeroSOuDA — Geração de CSV via Simulação ASA")
    _hr("=")
    print(f"  Cenário   : {json_path.name}")
    print(f"  Servidor  : {server_url}")
    print(f"  Saída CSV : {output_csv}")
    _hr()
    print()

    # ── Connect to ASA server ───────────────────────────────────────────────
    print("1/6  Conectando ao servidor ASA...")
    print("     Uma janela do navegador será aberta para autenticação.")
    print("     Se não abrir automaticamente, acesse o URL exibido a seguir.")
    print()

    try:
        asa = asaclient.ASA(server=server_url)
    except Exception as exc:
        print(f"\nERRO ao conectar ao servidor: {exc}", file=sys.stderr)
        print(
            "Verifique:\n"
            "  • Conexão com a internet / VPN\n"
            "  • URL do servidor\n"
            "  • Credenciais de acesso",
            file=sys.stderr,
        )
        sys.exit(1)

    print("     Conexão estabelecida.")
    print()

    # ── Load and save simulation ────────────────────────────────────────────
    print(f"2/6  Carregando simulação de {json_path.name}...")
    try:
        sim = asapy.load_simulation(str(json_path))
        sim = asa.save_simulation(sim)
        print(f"     Simulação salva no servidor (ID: {sim.id})")
    except Exception as exc:
        print(f"\nERRO ao carregar/salvar simulação: {exc}", file=sys.stderr)
        sys.exit(1)
    print()

    # ── Process aliases ──────────────────────────────────────────────────────
    print("3/6  Obtendo parâmetros configuráveis (aliases)...")
    try:
        doe = asapy.Doe()
        aliases = doe.process_aliases_by_sim(sim, asa.component_configs())
    except Exception as exc:
        print(f"\nERRO ao processar aliases: {exc}", file=sys.stderr)
        sys.exit(1)

    _hr()
    print("  Parâmetros disponíveis (aliases):")
    _hr()
    alias_names = list(aliases.index)
    for idx, alias_name in enumerate(alias_names):
        row = aliases.loc[alias_name]
        print(
            f"  {idx + 1:2d}.  {alias_name:<35s}"
            f"  padrão={row.get('default', '?'):<12}"
            f"  min={row.get('min', '?'):<12}"
            f"  max={row.get('max', '?')}"
        )
    _hr()
    print()

    # ── Interactive alias configuration ─────────────────────────────────────
    print("4/6  Configure os parâmetros do experimento.")
    print("     Pressione Enter para manter o valor atual.")
    print()

    while True:
        choice = _ask("Número do parâmetro a modificar (Enter para continuar)", "")
        if not choice:
            break

        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(alias_names)):
                raise ValueError
            alias_name = alias_names[idx]
        except ValueError:
            print("  Número inválido. Tente novamente.\n")
            continue

        row = aliases.loc[alias_name]
        print(f"\n  >>> {alias_name}")
        print(f"       atual  — min={row.get('min', '?')}, max={row.get('max', '?')}, "
              f"padrão={row.get('default', '?')}")

        for field in ("min", "max", "default"):
            current = row.get(field, "")
            raw = _ask(f"  Novo {field}", str(current) if current != "" else "")
            if raw and raw != str(current):
                try:
                    aliases.loc[alias_name, field] = float(raw)
                    print(f"       {field} atualizado para {float(raw)}")
                except ValueError:
                    print(f"       Valor inválido, mantendo {current}")
        print()

    # ── DOE creation ────────────────────────────────────────────────────────
    print()
    samples = _ask_int("Número de simulações (amostras DOE)", 30)
    seed = _ask_int("Seed do DOE (reprodutibilidade)", 42)

    print()
    print(f"5/6  Criando DOE com {samples} amostras (seed={seed})...")
    try:
        df_doe = doe.create(aliases, samples=samples, seed=seed)
        print(f"     DOE criado: {len(df_doe)} combinações de parâmetros.")
    except Exception as exc:
        print(f"\nERRO ao criar DOE: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Batch execution ──────────────────────────────────────────────────────
    print()
    print(f"6/6  Criando batch '{sim_name}' no servidor...")
    try:
        batch = asaclient.Batch(label=sim_name, simulation_id=sim.id)
        batch = asa.save_batch(batch)
        print(f"     Batch criado (ID: {batch.id})")
    except Exception as exc:
        print(f"\nERRO ao criar batch: {exc}", file=sys.stderr)
        sys.exit(1)

    chunk_size = _ask_int(
        "Simulações paralelas por chunk (menor = mais seguro, maior = mais rápido)",
        10,
    )

    print()
    print(f"     Executando {samples} simulações (chunk_size={chunk_size})...")
    print("     Isso pode demorar vários minutos. Aguarde...")
    print()

    try:
        ec = asapy.ExecutionController(
            sim_func=asapy.batch_simulate(batch=batch),
            stop_func=asapy.non_stop_func(),
            chunk_size=chunk_size,
        )
        results = ec.run(doe=df_doe)
        print(f"\n     Batch concluído! {len(results)} resultados obtidos.")
    except Exception as exc:
        print(f"\nERRO durante execução do batch: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Save results ─────────────────────────────────────────────────────────
    print()
    print(f"     Salvando resultados em: {output_csv}")
    try:
        results.to_csv(str(output_csv), index=False)
    except Exception as exc:
        print(f"\nERRO ao salvar CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    _hr("=")
    print("  CSV gerado com sucesso!")
    print(f"  Linhas: {len(results):,}")
    print(f"  Colunas: {', '.join(results.columns)}")
    _hr("=")
    print()

    # This sentinel line is parsed by cli.py to locate the output file
    print(f"OUTPUT_CSV:{output_csv}")


if __name__ == "__main__":
    main()
