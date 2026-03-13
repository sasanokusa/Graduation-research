from __future__ import annotations

import argparse
import json

from experimental.production_poc.adapters.action_guard import ActionGuard
from experimental.production_poc.adapters.backup_provider import NullBackupProvider
from experimental.production_poc.adapters.command_runner import SubprocessCommandRunner
from experimental.production_poc.adapters.host_observer import HostObserver
from experimental.production_poc.adapters.llm_analyzer import build_incident_analyzer
from experimental.production_poc.notifications.discord import build_notifier
from experimental.production_poc.runtime_prod.config import load_config
from experimental.production_poc.runtime_prod.controller import ProductionPocController
from experimental.production_poc.runtime_prod.persistence import StateStore


def build_controller(config_path: str, *, env_file: str | None = None) -> ProductionPocController:
    config = load_config(config_path, env_file=env_file)
    runner = SubprocessCommandRunner()
    store = StateStore(config.host.state_dir)
    notifier = build_notifier(
        config.notifications.discord_webhook_url,
        username=config.notifications.username,
    )
    observer = HostObserver(runner)
    guard = ActionGuard(config.actions, runner)
    analyzer = build_incident_analyzer(config.llm)
    return ProductionPocController(
        config=config,
        runner=runner,
        observer=observer,
        analyzer=analyzer,
        guard=guard,
        notifier=notifier,
        store=store,
        backup_provider=NullBackupProvider(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production emergency recovery PoC")
    parser.add_argument("--config", required=True, help="Path to production_poc YAML config")
    parser.add_argument("--env-file", default=None, help="Optional .env file for secrets")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("discover", help="Collect and persist a startup snapshot")
    subparsers.add_parser("monitor-once", help="Run one lightweight monitor iteration")
    args = parser.parse_args(argv)

    controller = build_controller(args.config, env_file=args.env_file)
    if args.command == "discover":
        snapshot = controller.run_discovery(notify=True)
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "monitor-once":
        outcome = controller.run_monitor_once()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
