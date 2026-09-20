"""Read configured test targets directly from an immutable Git tree."""
from .common import revision
from .evidence import GitSources
from .inventory import source_inventory


def open_index(store, config, ref='HEAD', *, native=False):
    rev = revision(store.root, ref)
    source = GitSources(store.root, rev, config['evaluator']['max_test_bytes'])
    inventory = source_inventory(store.root, config, snapshot=source, native=native)
    return source, inventory, {'basis': 'git', 'revision': rev,
                              'configuration_hash': config['config_hash'],
                              'target_count': sum(len(s['units']) for s in inventory['suites'])}
