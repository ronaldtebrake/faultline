"""The installed skill and standalone CLI share one install-to-report workflow."""
import re
import sys
import time
import uuid
from pathlib import Path

from .. import __version__
from ..core import FaultlineError, now, read_json, write_json
from ..credentials import api_key
from .batch import BatchedJev
from .benchmark import benchmark
from .benchmark_report import usage_metrics
from .common import checked, revision, save_frozen, seal
from .config import load_config
from .evidence import GitSources
from .progress import OptionalCache, Progress, RunBudget, run_lock
from .source_index import open_index


class NoAnswers:
    def get(self, key, qid):
        return None

    def put(self, value):
        raise FaultlineError('Preparation cannot save model answers')


def setup(store, *, sources=None, scope=None, ref='HEAD'):
    store.initialize()
    path = store.root / 'faultline.json'
    rev = revision(store.root, ref)
    if scope and not sources:
        raise FaultlineError('--scope requires --source when creating configuration; edit existing configuration directly')
    if sources:
        if path.exists():
            raise FaultlineError('faultline.json already exists; edit its reviewed suites instead of overwriting it')
        # Validate without installing runners or executing repository code.
        for pattern in [*sources, *(scope or [])]:
            if not pattern or Path(pattern).is_absolute() or '..' in Path(pattern).parts:
                raise FaultlineError('Source and scope patterns must be repository-relative')
        write_json(path, {'schema_version': 2, 'scope': scope or [],
                          'suites': [{'id': 'tests', 'sources': sources}]})
    if not path.exists():
        source = GitSources(store.root, rev)
        patterns = ['**/*Test.php', '**/*.feature', '**/*.test.ts', '**/*.test.tsx',
                    '**/*.spec.ts', '**/*.spec.tsx', '**/*.test.js', '**/*.spec.js',
                    '**/test_*.py', '**/*_test.py', '**/*_test.go', '**/*_spec.rb', '**/*Tests.cs']
        candidates = {p: source.glob([p]) for p in patterns}
        return {'complete': False, 'execution': 'none', 'jev_requests': 0,
                'candidate_sources': {p: files for p, files in candidates.items() if files},
                'next': 'Review candidates and missing test conventions; run setup --source <glob> --scope <glob>, or create faultline.json for multiple suites. Candidates are suggestions, not a complete inventory.'}
    config = load_config(store.root)
    _, inventory, index = open_index(store, config, rev)
    try:
        api_key(store)
        credential = 'available (not sent or validated)'
    except FaultlineError:
        credential = 'missing or unreadable; add TYPESAFE_API_KEY to .faultline/.env'
    return {'complete': inventory['complete'], 'execution': 'none', 'jev_requests': 0,
            'engine_version': __version__, 'credential': credential, 'configuration': str(path),
            'index': index, 'suites': inventory['suites'],
            'next': 'Review and commit faultline.json, then ask your agent to assess a PR.'}


def assess(store, *, base=None, head='HEAD', identifier=None, title='', description='',
           context_path=None, prepare=False, resume=None, reuse_cache=False, fresh=False,
           max_requests=None, selection_seconds=None, transport_factory=None):
    started = time.monotonic()
    store.initialize()
    config = load_config(store.root)
    ev = dict(config['evaluator'])
    if max_requests is not None:
        if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < 0:
            raise FaultlineError('max_requests must be a nonnegative integer')
        ev['jev_requests'] = max_requests
    if selection_seconds is not None:
        from ..core import number
        ev['selection_seconds'] = number(selection_seconds, 'selection_seconds')
    if fresh and (resume or reuse_cache):
        raise FaultlineError('--fresh starts new evidence; do not combine it with --resume or --reuse-cache')
    if prepare and resume:
        raise FaultlineError('Use report to inspect a saved run, or assess --resume to continue it')
    if resume and (base or context_path or identifier or title or description or reuse_cache or head != 'HEAD'):
        raise FaultlineError('--resume uses the saved revisions, metadata and context; omit new inputs')
    if not resume and not base:
        raise FaultlineError('Supply --base and the exact --head, or --resume <run-id>')
    run_id = resume or uuid.uuid4().hex
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise FaultlineError('Run ID must be the 32-character ID returned by assess')
    folder = store.path / 'runs' / run_id
    if resume and not (folder / 'run.json').exists():
        raise FaultlineError('Saved run was not found')
    if prepare:
        engine = BatchedJev(store, ev, answers=NoAnswers())
        return benchmark(store, base, head, identifier=identifier, title=title, description=description,
                         context_path=context_path, prepare=True, evaluator=engine,
                         max_requests=ev['jev_requests'], selection_seconds=ev['selection_seconds'])
    with run_lock(folder):
        if resume:
            meta = checked(folder / 'run.json', 'assessment-run')
            if meta['engine_version'] != __version__ or meta['config_hash'] != config['config_hash']:
                raise FaultlineError('Configuration or engine changed; start a new assessment')
            options = meta['options']
            if max_requests is None:
                ev['jev_requests'] = meta['request_ceiling']
            if selection_seconds is None:
                ev['selection_seconds'] = meta['selection_seconds']
            context_path = folder / 'context.json' if meta['context_integrity'] else None
            if context_path and checked(context_path, 'context_bundle')['integrity'] != meta['context_integrity']:
                raise FaultlineError('Saved context changed')
            reuse_cache = meta['reuse_cache']
        else:
            options = {'base': revision(store.root, base), 'head': revision(store.root, head),
                       'identifier': identifier, 'title': title, 'description': description}
            context = None
            if context_path:
                from .context import load
                from .selection import change
                context = load(context_path, change(store.root, options['base'], options['head']), config['repository'])
                save_frozen(folder / 'context.json', context)
                context_path = folder / 'context.json'
            meta = seal({'schema_version': 2, 'kind': 'assessment-run', 'created_at': now(),
                         'run_id': run_id, 'engine_version': __version__, 'options': options,
                         'config_hash': config['config_hash'], 'reuse_cache': reuse_cache,
                         'context_integrity': context['integrity'] if context else None,
                         'request_ceiling': ev['jev_requests'], 'selection_seconds': ev['selection_seconds']})
            save_frozen(folder / 'run.json', meta)
        cache = OptionalCache(store) if reuse_cache else None
        progress = Progress(folder, cache)
        if resume and max_requests is None and progress.request_ceiling is not None:
            ev['jev_requests'] = progress.request_ceiling
        if progress.request_ceiling != ev['jev_requests']:
            progress.append('ceiling', ev['jev_requests'])
        print(f'Faultline run {run_id}; resume with assess --resume {run_id}', file=sys.stderr)
        engine = BatchedJev(store, ev, answers=progress, budget=RunBudget(ev['jev_requests'], progress))
        if transport_factory:
            engine.http = transport_factory(engine)
        document = benchmark(store, **options, context_path=context_path, evaluator=engine,
                           max_requests=ev['jev_requests'], selection_seconds=ev['selection_seconds'],
                           run_progress=progress, document_only=True)
        document.pop('integrity')
        p = document['policies']['jev']
        p['requests'] = len(progress.attempts)
        p['usage'] = [a['usage'] for a in progress.attempts]
        p['cache_hits'] = len(progress.reused)
        metrics = usage_metrics(p, ev['pricing'])
        document['usage'].update({k: metrics[k] for k in ('requests', 'input_tokens', 'input_usd_estimate')})
        document['assessment'] = {'run_id': run_id, 'cache_policy': 'reuse-exact' if reuse_cache else 'fresh',
                                  'reused_answers': len(progress.reused), 'resumed_answers': len(progress.resumed),
                                  'new_answers': len(set(progress.answers) - progress.initial - progress.reused),
                                  'warnings': sorted(set(progress.warnings + (cache.warnings if cache else []))),
                                  'prior_invocation_seconds': sum(progress.elapsed),
                                  'agent_context_seconds': None,
                                  'agent_context_cost_usd': (document.get('context_bundle') or {}).get('collector', {}).get('cost_usd'),
                                  'timing_scope': 'Engine invocation through initial report generation. Agent investigation, installation and final metadata export are outside this clock.'}
        from .share_report import report
        # Render first, then freeze the elapsed engine time and report provenance.
        report(folder / 'pending.json', output=folder / 'report', document=seal(document))
        elapsed = time.monotonic() - started
        progress.append('elapsed', elapsed)
        document['assessment']['invocation_seconds'] = elapsed
        document = seal(document)
        destination = folder / (document['integrity'] + '.json')
        save_frozen(destination, document)
        write_json(folder / 'latest.json', {'benchmark': destination.name})
        final = report(destination, output=folder / 'report')
        return {**final, 'run_id': run_id, 'progress': str(progress.path),
                'resume': f'assess --resume {run_id}', 'assessment': document['assessment']}


def saved_report(store, *, path=None, run_id=None, output=None, demo=False):
    from .share_report import report, demo_report
    if demo:
        if path or run_id:
            raise FaultlineError('--demo cannot be combined with a saved assessment')
        return demo_report(output or store.path / 'demo.html')
    if bool(path) == bool(run_id):
        raise FaultlineError('Supply a frozen --benchmark or --run <run-id>')
    if run_id:
        if not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise FaultlineError('Invalid run ID')
        folder = store.path / 'runs' / run_id
        latest = read_json(folder / 'latest.json')
        if not latest or not re.fullmatch(r'[a-f0-9]{64}\.json', latest.get('benchmark', '')):
            raise FaultlineError('No frozen report yet; resume the interrupted assessment')
        path = folder / latest['benchmark']
    document = checked(path)
    if document.get('kind') == 'impact-assessment':
        from .impact_report import report as impact_report
        return impact_report(store, document, output or path.parent / 'report')
    return report(path, output=output)
