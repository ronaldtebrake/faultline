"""Small real check used to verify cross-job task-result transport."""
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
value = json.loads(source.read_text())['value']
assert isinstance(value, int) and value > 0
if source.stem == 'api':
    multiplier = json.loads(Path('data/shared.json').read_text())['multiplier']
    assert multiplier * value == 12
counter = Path('.faultline') / (source.stem + '-executions')
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')
print('Validated', source, 'execution', counter.read_text())
