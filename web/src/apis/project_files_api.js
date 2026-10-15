import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from './base'
const path = id => `/api/projects/${encodeURIComponent(id)}/files`
export const projectFilesApi = {
  list: (id, folder, search = '') => apiGet(`${path(id)}?${buildQuery({path:folder,search})}`),
  preview: (id, file) => apiGet(`${path(id)}/content?${buildQuery({path:file})}`, {}, true, 'blob'),
  save: (id, file, content) => apiPut(`${path(id)}/content`, {path:file,content}),
  mkdir: (id, parent, name) => apiPost(`${path(id)}/directory`, {parent_path:parent,name}),
  delete: (id, file) => apiDelete(`${path(id)}?${buildQuery({path:file})}`),
  download: (id, file) => apiGet(`${path(id)}/download?${buildQuery({path:file})}`, {}, true, 'blob'),
  upload(id, parent, files) { const data=new FormData(); data.append('parent_path',parent); for(const file of files) data.append('files',file); return apiPost(`${path(id)}/upload`,data) }
}
