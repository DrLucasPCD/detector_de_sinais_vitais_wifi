from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rf-sense", description="Agregador local RF Sense"
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="inicia API, UDP e dashboard")
    serve.add_argument("--host", default=None)
    serve.add_argument("--http-port", type=int, default=None)
    serve.add_argument("--udp-port", type=int, default=None)
    serve.add_argument("--simulate", action="store_true")
    serve.add_argument(
        "--scenario",
        choices=("cycle", "empty", "still", "moving"),
        default=None,
    )

    simulate = subparsers.add_parser("simulate", help="envia CSI sintético por UDP")
    simulate.add_argument("--host", default="127.0.0.1")
    simulate.add_argument("--port", type=int, default=5005)
    simulate.add_argument(
        "--scenario",
        choices=("cycle", "empty", "still", "moving"),
        default="cycle",
    )
    simulate.add_argument("--seed", type=int, default=42)
    simulate.add_argument("--node-id", type=int, default=1)
    simulate.add_argument("--fps", type=float, default=20.0)

    args = parser.parse_args()
    if args.command == "simulate":
        from .simulator import run_simulator
        import asyncio

        asyncio.run(
            run_simulator(
                host=args.host,
                port=args.port,
                scenario=args.scenario,
                seed=args.seed,
                node_id=args.node_id,
                fps=args.fps,
            )
        )
        return

    if getattr(args, "host", None):
        os.environ["RF_HTTP_HOST"] = args.host
    if getattr(args, "http_port", None):
        os.environ["RF_HTTP_PORT"] = str(args.http_port)
    if getattr(args, "udp_port", None):
        os.environ["RF_UDP_PORT"] = str(args.udp_port)
    if getattr(args, "simulate", False):
        os.environ["RF_SIMULATOR"] = "1"
    if getattr(args, "scenario", None):
        os.environ["RF_SIMULATOR_SCENARIO"] = args.scenario

    import uvicorn

    host = os.getenv("RF_HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("RF_HTTP_PORT", "8000"))
    uvicorn.run("rf_sense.api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

