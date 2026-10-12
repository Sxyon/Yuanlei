import { resolve, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { writeFileSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
const root = dirname(fileURLToPath(import.meta.url))
if (!process.env.S02_TINY_PACKAGE) throw Error('S02_TINY_PACKAGE_required')
const { genSFCWithDefaultPlugin } = await import(pathToFileURL(resolve(process.env.S02_TINY_PACKAGE, 'dist/tiny-engine-dsl-vue.js')))
const schema = JSON.parse(readFileSync(resolve(root, 'tiny-schema.json'), 'utf8'))
const output = genSFCWithDefaultPlugin(schema, [])
writeFileSync(resolve(root, 'TinyGenerated.vue'), output + '\n')
const result = {
  package: '@opentiny/tiny-engine-dsl-vue', version: '2.11.0',
  method: 'genSFCWithDefaultPlugin with official defaults; synthetic literals; no generated code edited',
  bytes: Buffer.byteLength(output + '\n'), sha256: createHash('sha256').update(output + '\n').digest('hex'),
  importsVueI18n: output.includes('from "vue-i18n"'), requiresLowcodeInjection: output.includes('vue.inject(I18nInjectionKey).lowcode()'),
  directHostCompatible: false, runtime: 'Not run: default output depends on unavailable host context'
}
writeFileSync(resolve(root, '../../tiny-generation.json'), JSON.stringify(result, null, 2) + '\n')
console.log(JSON.stringify(result, null, 2))
