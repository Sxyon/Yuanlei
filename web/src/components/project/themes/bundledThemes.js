import defaultManifest from './packages/default/manifest.json'
import defaultTheme from './packages/default/theme.json'
import researchManifest from './packages/research/manifest.json'
import researchTheme from './packages/research/theme.json'
import defaultArchive from './packages/default.theme.zip?url'
import researchArchive from './packages/research.theme.zip?url'
import surveyImage from './packages/research/assets/survey.png?url'
import { sha256, validateThemePackage } from './contract'

const samples = [
  { reference: 'sample-default', manifest: defaultManifest, theme: defaultTheme, archive: defaultArchive, assets: {} },
  { reference: 'sample-research', manifest: researchManifest, theme: researchTheme, archive: researchArchive, assets: { distribution: surveyImage } }
]
export const bundledThemeCatalog = samples.map(sample => ({ id: sample.reference, name: sample.theme.name }))

/** 内置样例加载器可被S04已授权版本加载替换；宿主不识别主题ID。 */
export const bundledThemeLoader = {
  async load({ selectionId, signal }) {
    const sample = samples.find(item => item.reference === selectionId)
    if (!sample) throw new Error('主题包不存在')
    const response = await fetch(sample.archive, { signal })
    if (!response.ok) throw new Error('主题包读取失败')
    const bytes = new Uint8Array(await response.arrayBuffer())
    return { ...validateThemePackage({ manifest: sample.manifest, theme: sample.theme }), reference: sample.reference, digest: await sha256(bytes) }
  },
  async readAsset({ digest, reference, alias, signal }) {
    const sample = samples.find(item => item.reference === reference)
    const loaded = await this.load({ selectionId: reference, signal })
    if (loaded.digest !== digest || !sample.assets[alias]) return { state: 'missing', message: '包内资源不存在或包已变化' }
    const response = await fetch(sample.assets[alias], { signal })
    if (!response.ok) return { state: 'error', message: '包内资源读取失败' }
    const bytes = new Uint8Array(await response.arrayBuffer())
    const asset = loaded.manifest.assets[alias]
    return { state: 'ready', bytes, metadata: { mediaType: asset.mediaType, size: bytes.length, sha256: asset.sha256 } }
  }
}
