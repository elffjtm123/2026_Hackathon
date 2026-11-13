import { cp, mkdir, stat, readFile, writeFile } from 'node:fs/promises';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const target = resolve(root, 'public/pulse-assets');
await mkdir(target, {recursive: true});
await cp(resolve(root, 'node_modules/@mediapipe/tasks-vision/wasm'), resolve(target, 'wasm'), {recursive: true});
await cp(resolve(root, 'node_modules/@mediapipe/tasks-vision/vision_bundle.js'), resolve(target, 'vision_bundle.js'));
// Classic worker is required by MediaPipe's documented importScripts WASM loader.
const source = (await readFile(resolve(root, 'src/features/pulse/signal.ts'), 'utf8')).replace(/^export /gm, '');
const signal = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None}}).outputText;
await writeFile(resolve(target, 'signal.js'), `(() => {\n${signal}\nself.PulseSignal = { PulseBuffer, estimatePulse, emptyPulse, estimateNeuralPulse, mergeNeuralWindow, PulseSmoother };\n})();\n`);
const regionSource = (await readFile(resolve(root, 'src/features/pulse/regions.ts'), 'utf8')).replace(/^export /gm, '');
const regionJs = ts.transpileModule(regionSource, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None}}).outputText;
await writeFile(resolve(target, 'regions.js'), `(() => {\n${regionJs}\nself.PulseRegions = { pulseRegions, FaceCropTracker };\n})();\n`);
const featureSource = (await readFile(resolve(root, 'src/features/face-features/features.ts'), 'utf8')).replace(/^export /gm, '');
const featureJs = ts.transpileModule(featureSource, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None}}).outputText;
await writeFile(resolve(target, 'face-features.js'), `(() => {\n${featureJs}\nself.FaceFeatures = { FaceFeatureTracker };\n})();\n`);
const model = resolve(root, '.models/face_landmarker.task');
try {
  if (!(await stat(model)).size) throw new Error('Empty model');
  await cp(model, resolve(target, 'face_landmarker.task'));
  console.log('Pulse assets prepared locally; no runtime CDN is used.');
} catch {
  console.warn('Pulse disabled: place the official MediaPipe face_landmarker.task in .models/ then run npm run prepare:pulse-assets.');
}
