/** 平台可信页面版本；主题仅重排、命名与选择这些能力。 */
export const baseWorkspacePages = Object.freeze([
  {
    capability: 'overview',
    id: 'overview',
    title: '总览',
    group: '方向与思考',
    route: 'ProjectDashboardComp'
  },
  {
    capability: 'blueprints',
    id: 'blueprints',
    title: '蓝图',
    group: '方向与思考',
    route: 'ProjectBlueprints'
  },
  {
    capability: 'topics',
    id: 'topics',
    title: '议题',
    group: '方向与思考',
    route: 'ProjectTopics'
  },
  {
    capability: 'plans',
    id: 'plans',
    title: '行动计划',
    group: '行动与反馈',
    route: 'ProjectPlans'
  },
  {
    capability: 'work',
    id: 'work',
    title: '工作',
    group: '行动与反馈',
    route: 'ProjectWorkTasksView'
  },
  {
    capability: 'inspection',
    id: 'inspection',
    title: '督查',
    group: '行动与反馈',
    route: 'ProjectReports'
  },
  { capability: 'files', id: 'files', title: '资料', group: '项目资源', route: 'ProjectFiles' },
  {
    capability: 'agents',
    id: 'agents',
    title: '智能体',
    group: '项目资源',
    route: 'ProjectAgentsComp'
  },
  {
    capability: 'settings',
    id: 'settings',
    title: '设置',
    group: '项目资源',
    route: 'ProjectSettings'
  }
])

/** 缺失能力明确继承基础界面；包中页面ID不决定业务身份。 */
export function resolveWorkspacePages(pack) {
  const overrides = (pack?.theme.pages || []).filter((page) => page.capability)
  const overridden = new Set(overrides.map((page) => page.capability))
  return [
    ...overrides.map((page) => ({
      ...baseWorkspacePages.find((base) => base.capability === page.capability),
      ...page,
      inherited: false
    })),
    ...baseWorkspacePages
      .filter((page) => !overridden.has(page.capability))
      .map((page) => ({ ...page, inherited: true }))
  ]
}

/** 路由详情属于同一业务能力，保持对象参数与锚点。 */
export function routeCapability(name) {
  if (name === 'ProjectWorkTaskView') return 'work'
  if (name === 'ProjectAgentWorkbenchView') return 'agents'
  return baseWorkspacePages.find((page) => page.route === name)?.capability
}

/** 新能力主题的历史展示书签进入真实业务消费者，保留原定位。 */
export function legacyThemeTarget(pack, route) {
  if (pack?.manifest?.componentAbi !== 2) return null
  const declared = pack.theme.pages.find((item) => item.id === route.query.theme_page)
  if (declared && !declared.capability) return null
  const pages = resolveWorkspacePages(pack)
  const page = route.query.theme_page
    ? pages.find((item) => item.id === route.query.theme_page)
    : pages.find((item) => item.capability === 'overview')
  if (!page) return null
  return {
    name: page.route,
    params: { project_id: route.params.project_id },
    query: { ...route.query, theme_page: page.id },
    hash: route.hash || ''
  }
}

/** 项目列表编辑只进入当前主题明确声明的设置页，否则使用原弹窗。 */
export function projectThemeSettingsTarget(projectId, pack) {
  const page = pack?.theme.pages.find(item => item.capability === 'settings')
  return page ? { name: 'ProjectSettings', params: { project_id: projectId }, query: { theme_page: page.id } } : null
}
