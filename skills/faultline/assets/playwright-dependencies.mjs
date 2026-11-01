/** Extend the project's existing test fixture; no browser is forced for API-only tests. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {sourceResolver} from './playwright_source.mjs';

export function withFaultline(base) {
  return base.extend({
    faultlineDependencies: [
    // oxlint-disable-next-line no-empty-pattern -- Playwright requires a destructured fixture parameter.
    async ({}, use, testInfo) => {
      const contextPath = process.env.FAULTLINE_DEPENDENCY_CONTEXT;
      if (!contextPath) {
        await use({ file() {}, request() {}, requestContext(value) { return value; } });
        return;
      }
      const directory = process.env.FAULTLINE_DEPENDENCY_OUTPUT;
      if (!directory) throw new Error('Set FAULTLINE_DEPENDENCY_OUTPUT for runtime evidence');
      const context = JSON.parse(fs.readFileSync(contextPath, 'utf8'));
      const identity = sourceResolver(context)(testInfo);
      const files = new Set(Object.keys(identity.generation?.inputs ?? {}));
      const resources = new Map();
      const gaps = new Set(['Requests may be mocked; server-side source execution is not observed.']);
      const relative = file => path.relative(context.root, path.resolve(file)).split(path.sep).join('/');
      const source = relative(identity.file);
      if (!context.sources.includes(source) || [...files].some(file => !Object.hasOwn(context.tree, file))) {
        throw new Error('Faultline test or generation input is outside its source snapshot');
      }
      if (identity.generation) gaps.add('Generation bindings are declared inputs, not observed server-side coverage.');
      const collector = {
        file(file) {
          const name = relative(file);
          if (Object.hasOwn(context.tree, name)) files.add(name);
          else gaps.add('Dependency is outside tracked repository source.');
        },
        request(method, address) {
          try {
            const url = new URL(address);
            if (!['http:', 'https:'].includes(url.protocol)) return;
            // Do not persist hosts, user info, query strings, headers, or bodies.
            const item = { kind: 'http_request', method: method.toUpperCase(), path: url.pathname };
            resources.set(JSON.stringify(item), item);
          } catch {
            gaps.add('A request URL could not be interpreted.');
          }
        },
        requestContext(client, baseURL) {
          // Explicit wrapping leaves the original context and its cookie jar
          // untouched. Bind native methods to their original receiver.
          const verbs = new Set(['fetch', 'get', 'post', 'put', 'patch', 'delete', 'head']);
          return new Proxy(client, {
            get(target, key) {
              const value = Reflect.get(target, key, target);
              if (typeof value !== 'function') return value;
              if (!verbs.has(key)) return value.bind(target);
              return (...args) => {
                const [address, options] = args;
                try {
                  const url = typeof address === 'string' ? address : address.url();
                  const method = key === 'fetch'
                    ? options?.method ?? (typeof address === 'string' ? 'GET' : address.method())
                    : key.toUpperCase();
                  collector.request(method, new URL(url, baseURL).href);
                } catch {
                  gaps.add('An API request could not be attributed; its native call was preserved.');
                }
                return Reflect.apply(value, target, args);
              };
            },
          });
        },
      };
      try {
        await use(collector);
      } finally {
        const record = {
          version: 1, context: context.integrity, producer: 'playwright', test_source: source,
          test_identity: JSON.stringify([testInfo.project.name, testInfo.titlePath, testInfo.line, testInfo.column, testInfo.repeatEachIndex]),
          retry: testInfo.retry, status: testInfo.status || 'unknown', files: [...files].sort(),
          resources: [...resources.values()], gaps: [...gaps],
          ...(identity.generation ? {generation: identity.generation} : {}),
        };
        fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
        fs.writeFileSync(path.join(directory, `playwright-${crypto.randomUUID()}.json`), JSON.stringify(record), { flag: 'wx' });
      }
    }, { auto: true }],
    context: async ({ context, faultlineDependencies }, use) => {
      const observe = request => faultlineDependencies.request(request.method(), request.url());
      context.on('request', observe);
      try { await use(context); }
      finally { context.off('request', observe); }
    },
  });
}
