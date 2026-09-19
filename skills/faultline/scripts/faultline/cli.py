"""Deterministic CLI shared by Faultline agent workflows and local tooling."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import DEFAULTS, FaultlineError, Store, read_json, repo_root, write_json
from .evaluation import evaluate
from .index import build_index, index_status, load_profiles, source_hash
from .jev import LEVELS, validate_answer
from .report import aggregate, regenerate
from .tia.cli import COMMANDS as TIA_COMMANDS, add_commands, dispatch
from .workflow import load_prediction, prediction_path, rank


def parser():
    cli = argparse.ArgumentParser(prog='faultline', description='Deterministic core for the Faultline Agent Skills')
    cli.add_argument('--root', default='.', help='Target repository (defaults to the current Git root)')
    cli.add_argument('--version', action='version', version='faultline 0.1.0')
    commands = cli.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Initialize ignored local storage and configuration')
    commands.add_parser('index-status', help='List unchanged, changed, and missing profile sources')
    indexing = commands.add_parser('index', help='Validate and save a complete agent-authored catalog')
    indexing.add_argument('action', nargs='?', choices=['show'])
    indexing.add_argument('--input', type=Path)
    indexing.add_argument('--agent', default='unspecified')
    indexing.add_argument('--rewrite', action='store_true', help='Replace unchanged descriptions after an intentional review')
    inspect = commands.add_parser('explain-test')
    inspect.add_argument('id')
    hashing = commands.add_parser('source-hash', help='Hash source and relevant setup/helpers deterministically')
    hashing.add_argument('source')
    hashing.add_argument('--context', action='append', default=[])
    for name in ('rank', 'jev-evaluate'):
        ranking = commands.add_parser(name, help='Rank supplied change context; freeze probabilities and write ranking report')
        ranking.add_argument('--change', required=True, type=Path)
        ranking.add_argument('--tests', type=Path)
        ranking.add_argument('--dry-run', action='store_true')
        ranking.add_argument('--max-requests', type=int)
    scoring = commands.add_parser('score', help='Validate a distribution and compute its expected relevance value')
    scoring.add_argument('--input', required=True, type=Path)
    evaluation = commands.add_parser('evaluate', help='Compare frozen predictions with subsequently collected outcomes and save reports')
    evaluation.add_argument('--prediction', required=True)
    evaluation.add_argument('--outcomes', required=True, type=Path)
    report = commands.add_parser('report', help='Regenerate one case report or aggregate all saved cases, offline')
    report.add_argument('--prediction')
    add_commands(commands)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    store = Store(repo_root(args.root))
    try:
        if args.command in TIA_COMMANDS:
            result = dispatch(store, args)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 2 if result.get('complete') is False else 0
        config = store.config()
        if args.command == 'init':
            store.initialize()
            path = store.path / 'config.json'
            if not path.exists():
                write_json(path, DEFAULTS)
            result = {'config': str(path), 'index': str(store.path / 'index.jsonl')}
        elif args.command == 'source-hash':
            result = {'source_hash': source_hash(store.root, args.source, args.context)}
        elif args.command == 'index-status':
            result = index_status(store)
        elif args.command == 'index':
            if args.action == 'show':
                result = load_profiles(store.path / 'index.jsonl')
            elif args.input:
                result = build_index(store, args.input, args.agent, args.rewrite)
            else:
                raise FaultlineError('Use index --input <complete-catalog.jsonl> --agent <name>, or index show')
        elif args.command == 'explain-test':
            result = next((p for p in load_profiles(store.path / 'index.jsonl') if p['id'] == args.id), None)
            if result is None:
                raise FaultlineError('Test ID not in catalog')
        elif args.command in ('rank', 'jev-evaluate'):
            if args.max_requests is not None:
                if args.max_requests < 0:
                    raise FaultlineError('--max-requests cannot be negative')
                config['jev_requests'] = args.max_requests
            result = rank(store, args.change, args.tests, dry_run=args.dry_run, config=config)
        elif args.command == 'score':
            probabilities = read_json(args.input)
            if not isinstance(probabilities, dict) or set(probabilities) != set(LEVELS):
                raise FaultlineError('Expected exactly the five relevance probabilities')
            response = {'model': config['model'], 'answers': {'relevance': {
                'type': 'choice', 'choice': 'irrelevant', 'probabilities': probabilities}}}
            result = validate_answer(response, config['model'])
            result.pop('choice', None)
        elif args.command == 'evaluate':
            result = evaluate(store, prediction_path(store, args.prediction), args.outcomes, config)
        elif args.command == 'report':
            if args.prediction:
                document = load_prediction(prediction_path(store, args.prediction))
                result = regenerate(store, document['prediction_id'])
            else:
                result = aggregate(store)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2 if isinstance(result, dict) and result.get('complete') is False else 0
    except (FaultlineError, OSError) as exc:
        print(f'faultline: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('faultline: interrupted; completed cache entries are retained.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
