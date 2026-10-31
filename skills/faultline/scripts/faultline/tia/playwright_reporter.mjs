// Native test identities and results. Never export test output, errors or secrets.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {sourceResolver} from './playwright_source.mjs';

export default class FaultlineReporter {
  constructor(options) {
    this.options = options;
    this.errors = 0;
    this.selectionApplied = options.files === null;
    this.resolveSource = sourceResolver(options);
    this.sources = new Map();
  }

  async preprocess({config, suite, testRun}) {
    const retained = this.options.files === null ? null : new Set(this.options.files.map(file => path.resolve(file)));
    // The native runner owns setup, dependency and teardown project lifecycles.
    const protectedProjects = new Set(config.projects.flatMap(project =>
      [...project.dependencies, ...(project.teardown ? [project.teardown] : [])]));
    const nativeHashes = new Map();
    for (const test of suite.allTests()) {
      const source = this.resolveSource(test);
      const nativeFile = test.location.file;
      if (!nativeHashes.has(nativeFile)) {
        nativeHashes.set(nativeFile, crypto.createHash('sha256').update(fs.readFileSync(nativeFile)).digest('hex'));
      }
      const support = protectedProjects.has(test.parent.project()?.name);
      this.sources.set(test.id + ':' + test.repeatEachIndex,
        {...source, nativeFile, nativeSha256: nativeHashes.get(nativeFile), support});
      if (retained !== null && !support && !retained.has(path.resolve(source.file))) {
        testRun.exclude(test);
      }
    }
    this.selectionApplied = true;
  }

  onBegin(config, suite) {
    this.config = config;
    this.suite = suite;
  }

  onError() { this.errors += 1; }

  onEnd(result) {
    if (!this.suite) return;
    const resolve = sourceResolver(this.options);
    const hashes = new Map();
    const tests = this.suite.allTests().map(test => {
      const native = test.location.file;
      if (!hashes.has(native)) hashes.set(native, crypto.createHash('sha256').update(fs.readFileSync(native)).digest('hex'));
      return {
        id: test.id + ':' + test.repeatEachIndex,
        ...this.sources.get(test.id + ':' + test.repeatEachIndex),
        ...resolve(test),
        nativeSha256: hashes.get(native),
        project: test.parent.project()?.name ?? '',
        title: test.titlePath().join(' > '),
        expectedStatus: test.expectedStatus,
        outcome: test.outcome(),
        attempts: test.results.map(attempt => ({retry: attempt.retry, status: attempt.status, duration: attempt.duration}))
      };
    });
    const report = {version: 2, complete: true, runnerVersion: this.config.version,
      selectionApplied: this.selectionApplied, status: result.status, errors: this.errors, tests};
    fs.mkdirSync(path.dirname(this.options.output), {recursive: true});
    fs.writeFileSync(this.options.output + '.tmp', JSON.stringify(report));
    fs.renameSync(this.options.output + '.tmp', this.options.output);
  }

  printsToStdio() { return false; }
}
