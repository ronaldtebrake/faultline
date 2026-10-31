// A generator-owned declaration, validated independently of failure source maps.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const SOURCE_ANNOTATION = 'faultline-source';
const MAX_BYTES = 128 * 1024;
const MAX_INPUTS = 512;
const MAX_ARTIFACT_BYTES = 16 * 1024 * 1024;
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function relativeFile(root, name) {
  if (typeof name !== 'string' || !name || /[\\:\x00-\x1f]/.test(name) ||
      name.split('/').some(part => !part || part === '.' || part === '..')) {
    throw new Error('Faultline generation inputs require canonical repository-relative paths');
  }
  const file = path.join(root, name);
  if (!fs.lstatSync(file).isFile() || path.relative(root, fs.realpathSync(file)).split(path.sep).join('/') !== name) {
    throw new Error('Faultline generation input is not a regular file inside the repository');
  }
  return file;
}

function shape(mapping, revision) {
  const artifacts = mapping?.version === 2 ? mapping.artifacts : {};
  if (!mapping || typeof mapping !== 'object' || Array.isArray(mapping) ||
      Object.keys(mapping).sort().join(',') !== (mapping.version === 2 ? 'artifacts,inputs,revision,source,version' : 'inputs,revision,source,version') ||
      ![1, 2].includes(mapping.version) || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(mapping.revision) ||
      mapping.revision !== revision || !mapping.inputs || typeof mapping.inputs !== 'object' ||
      Array.isArray(mapping.inputs) || !Object.hasOwn(mapping.inputs, mapping.source) ||
      !artifacts || typeof artifacts !== 'object' || Array.isArray(artifacts) ||
      (mapping.version === 2 && !Object.keys(artifacts).length) ||
      Object.keys(artifacts).some(name => Object.hasOwn(mapping.inputs, name)) ||
      Object.keys(mapping.inputs).length + Object.keys(artifacts).length > MAX_INPUTS ||
      [...Object.values(mapping.inputs), ...Object.values(artifacts)].some(value => typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) ||
      Buffer.byteLength(JSON.stringify(mapping)) > MAX_BYTES) {
    throw new Error('Invalid or stale Faultline generated-source declaration');
  }
}

/** Call during generation and embed the returned literal in the generated test. */
export function sourceAnnotation({root, revision, source, inputs, artifacts = []}) {
  root = fs.realpathSync(root);
  if (!Array.isArray(inputs) || !inputs.length) throw new Error('Declare the generator and resolved step/setup inputs');
  const names = [...new Set([source, ...inputs])].sort();
  if (!Array.isArray(artifacts)) throw new Error('Declare artifact paths as an array');
  artifacts = [...new Set(artifacts)].sort();
  if (names.length + artifacts.length > MAX_INPUTS) throw new Error('Too many generation inputs; no inputs were truncated');
  const mapping = {version: artifacts.length ? 2 : 1, revision, source,
    inputs: Object.fromEntries(names.map(name => [name, hash(fs.readFileSync(relativeFile(root, name)))]))};
  if (artifacts.length) mapping.artifacts = Object.fromEntries(artifacts.map(name => {
    const file = relativeFile(root, name);
    if (fs.statSync(file).size > MAX_ARTIFACT_BYTES) throw new Error('Generation artifact exceeds the size limit');
    return [name, hash(fs.readFileSync(file))];
  }));
  shape(mapping, revision);
  return {type: SOURCE_ANNOTATION, description: JSON.stringify(mapping)};
}

/** Shared by native discovery and runtime collection. Python verifies tracked inputs too. */
export function sourceResolver({root, revision}) {
  root = fs.realpathSync(root);
  const validated = new Map();
  const hashes = new Map();
  return test => {
    const annotations = (test.annotations ?? []).filter(item => item.type === SOURCE_ANNOTATION);
    if (annotations.length > 1) throw new Error('Ambiguous Faultline generated-source declarations');
    const nativeFile = test.location?.file ?? test.file;
    if (!annotations.length) return {file: nativeFile, generation: null};
    const description = annotations[0].description;
    if (typeof description !== 'string' || Buffer.byteLength(description) > MAX_BYTES) {
      throw new Error('Invalid Faultline generated-source declaration');
    }
    let mapping = validated.get(description);
    if (!mapping) {
      mapping = JSON.parse(description);
      shape(mapping, revision);
      for (const [name, expected] of Object.entries({...mapping.inputs, ...mapping.artifacts})) {
        const file = relativeFile(root, name);
        if (Object.hasOwn(mapping.artifacts ?? {}, name) && fs.statSync(file).size > MAX_ARTIFACT_BYTES) {
          throw new Error('Generation artifact exceeds the size limit');
        }
        if (!hashes.has(name)) hashes.set(name, hash(fs.readFileSync(file)));
        if (hashes.get(name) !== expected) throw new Error('Faultline generation input changed; regenerate tests');
      }
      validated.set(description, mapping);
    }
    return {file: relativeFile(root, mapping.source), generation: mapping};
  };
}
