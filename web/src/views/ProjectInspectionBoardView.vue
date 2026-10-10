<template>
  <div class="inspection-page">
    <PageHeader :title="pageTitle" :loading="loading" show-border>
      <template #actions>
        <a-button
          size="small"
          @click="router.push({ name: 'ProjectDashboardComp', params: { project_id: projectId } })"
          >项目概览</a-button
        >
        <a-button size="small" @click="router.push({ name: 'InspectionBoardComp' })"
          >返回督查板</a-button
        >
        <a-button size="small" :disabled="loading || busy" @click="load">刷新</a-button>
      </template>
    </PageHeader>

    <div ref="scrollContainer" class="inspection-body">
      <a-spin v-if="loading" class="inspection-state" />
      <a-alert
        v-else-if="errorMessage"
        type="error"
        show-icon
        message="项目工作台加载失败"
        :description="errorMessage"
      >
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <div v-if="!errorMessage" v-show="!loading" class="workbench-content">
        <a-alert
          v-if="actionError"
          type="error"
          show-icon
          :message="actionError"
          closable
          @close="actionError = ''"
        />
        <header class="workbench-intro">
          <div>
            <p class="workbench-kicker">PROJECT WORKBENCH</p>
            <h1>{{ board.project?.name || '项目工作台' }}</h1>
            <p>维护蓝图、研讨议题与批准决策，将建议纳入正式工作。独立人工事项可直接在工作页创建；交付与验收在准确工作详情办理。</p>
          </div>
          <div class="workbench-links">
            <RouterLink :to="{ name: 'ProjectWorkTasksView', params: { project_id: projectId } }"
              >项目工作任务</RouterLink
            >
            <RouterLink :to="{ name: 'AgentManageComp', query: { tab: 'projects' } }"
              >项目数字员工</RouterLink
            >
            <RouterLink :to="{ name: 'AgentManageComp', query: { tab: 'schedules' } }"
              >定时汇报</RouterLink
            >
          </div>
        </header>
        <nav class="workbench-nav" aria-label="工作台栏目">
          <button
            v-for="item in sectionLinks"
            :key="item.id"
            type="button"
            :aria-pressed="activeSection === item.id"
            @click="navigateSection(item.id)"
          >
            {{ item.label }}
          </button>
        </nav>

        <section id="blueprint" v-show="activeSection === 'blueprint'" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">01</span>
            <div>
              <h2>项目蓝图</h2>
              <p>记录目标、范围和验收标准</p>
            </div>
          </div>
          <a-alert
            v-if="blueprintActionError"
            type="error"
            show-icon
            :message="blueprintActionError"
            closable
            @close="blueprintActionError = ''"
          />
          <div class="form-row">
            <a-select
              v-model:value="blueprintName"
              :disabled="busy || loading"
              placeholder="选择当前蓝图"
              style="min-width: 200px"
              @change="readBlueprint"
            >
              <a-select-option v-for="doc in blueprints" :key="doc.name" :value="doc.name">{{
                displayBlueprintName(doc.name)
              }}</a-select-option>
            </a-select>
            <a-button :disabled="busy || loading" @click="openCreateBlueprint">新建蓝图</a-button>
          </div>
          <a-alert v-if="sharedBlueprintDirectory" type="info" show-icon message="这些项目共用目录，蓝图文件可能共享。修改、重命名和归档会作用于同一份文件。" class="blueprint-shared-hint" />
          <div v-if="blueprintName && !blueprintEditing" class="blueprint-reader">
            <MarkdownPreview :content="blueprintContent || '这份蓝图尚无正文。'" />
            <a-button :disabled="busy || loading" @click="blueprintEditing = true">编辑蓝图</a-button>
            <span v-if="blueprintContent !== savedBlueprintContent" class="hint">已恢复未保存草稿；尚未写入蓝图。</span>
          </div>
          <p v-else-if="!blueprintName" class="hint">暂无蓝图，可新建并记录项目目标与计划。</p>
          <a-textarea v-show="blueprintName && blueprintEditing"
            v-model:value="blueprintContent"
            aria-label="蓝图正文"
            :rows="9"
            :disabled="!blueprintName"
            placeholder="在这里编辑项目目标、范围、验收标准与执行计划"
          />
          <div class="form-row">
            <a-button
              type="primary"
              v-if="blueprintEditing"
              :disabled="!blueprintName || !blueprints.some(doc => doc.name === loadedBlueprintName) || blueprintName !== loadedBlueprintName || busy || loading"
              @click="saveBlueprint"
              >保存蓝图</a-button
            ><a-button v-if="blueprintEditing" :disabled="busy" @click="blueprintEditing = false">返回阅读（保留草稿）</a-button><span v-if="blueprintEditing && blueprintContent !== savedBlueprintContent" class="hint"
              >有未保存的蓝图草稿</span
            ><span v-else-if="blueprintEditing" class="hint">保存后从项目 Workdir 回读。</span>
            <a-dropdown v-if="blueprintName" :trigger="['click']" placement="bottomRight">
              <a-button
                class="blueprint-more"
                :disabled="blueprintName !== loadedBlueprintName || busy || loading"
                aria-label="蓝图更多操作"
                ><Ellipsis :size="16" />更多</a-button
              >
              <template #overlay>
                <a-menu @click="handleBlueprintMenu">
                  <a-menu-item key="rename"
                    ><template #icon><Pencil :size="15" /></template>重命名</a-menu-item
                  >
                  <a-menu-item key="archive"
                    ><template #icon><Archive :size="15" /></template>归档</a-menu-item
                  >
                  <a-menu-divider />
                  <a-menu-item key="delete" danger
                    ><template #icon><Trash2 :size="15" /></template>永久删除</a-menu-item
                  >
                </a-menu>
              </template>
            </a-dropdown>
          </div>
          <details class="blueprint-history" :open="!!selectedArchive">
            <summary>历史蓝图 · {{ archivedBlueprints.length }} 份</summary>
            <h3>
              历史蓝图 <span>{{ archivedBlueprints.length }}</span>
            </h3>
            <p v-if="!archivedBlueprints.length" class="hint">
              暂无归档蓝图。旧蓝图归档后会在这里保留供翻阅。
            </p>
            <div v-else class="archive-layout">
              <div class="archive-list" aria-label="历史蓝图列表">
                <button
                  v-for="archive in archivedBlueprints"
                  :key="archive.archive_name"
                  type="button"
                  :class="{ active: selectedArchive === archive.archive_name }"
                  @click="readArchive(archive.archive_name)"
                >
                  <strong>{{ displayBlueprintName(archive.name) }}</strong
                  ><small>{{ archiveTimeLabel(archive.archived_at) }}</small>
                </button>
              </div>
              <div class="archive-preview">
                <div v-if="selectedArchive" class="archive-preview-heading">
                  <span>归档内容 · 只读</span>
                  <a-button
                    type="text"
                    size="small"
                    :disabled="busy || loading || archiveLoading"
                    @click="openBlueprintDelete(true)"
                  >
                    <Trash2 :size="14" />删除
                  </a-button>
                </div>
                <a-spin v-if="archiveLoading" />
                <a-alert v-else-if="archiveError" type="error" show-icon :message="archiveError" />
                <MarkdownPreview v-else-if="archiveContent" :content="archiveContent" />
                <p v-else class="hint">选择一份历史蓝图查看内容。</p>
              </div>
            </div>
          </details>
        </section>

        <a-modal v-model:open="createBlueprintOpen" title="新建蓝图" :width="760" :mask-closable="false" :confirm-loading="busy" :ok-button-props="{ disabled: busy }" :cancel-button-props="{ disabled: busy }" ok-text="创建蓝图" cancel-text="取消" @ok="createBlueprint">
          <a-form layout="vertical">
            <a-form-item label="蓝图名称" required>
              <a-input v-model:value="newBlueprintName" aria-label="新蓝图名称" placeholder="例如 API设计方案" :disabled="busy" />
              <p class="hint">名称不含空格；支持中文、英文、数字和常用标点。</p>
            </a-form-item>
            <a-form-item label="起草模板">
              <a-select :value="newBlueprintTemplate" :options="blueprintTemplates" :disabled="busy" @change="changeBlueprintTemplate" />
              <p class="hint">模板是可编辑的 Markdown 正文，可按需要增删内容。</p>
            </a-form-item>
            <a-form-item label="蓝图正文">
              <a-textarea v-model:value="newBlueprintContent" aria-label="新蓝图正文" :rows="12" :disabled="busy" placeholder="输入项目目标、范围与计划" />
            </a-form-item>
          </a-form>
          <a-alert v-if="createBlueprintError" type="error" show-icon :message="createBlueprintError" />
        </a-modal>
        <a-modal
          v-model:open="renameBlueprintOpen"
          title="重命名蓝图"
          ok-text="保存名称"
          cancel-text="取消"
          :confirm-loading="busy"
          :ok-button-props="{ disabled: busy || !renameBlueprintDraft.trim() }"
          :cancel-button-props="{ disabled: busy }"
          :mask-closable="!busy"
          :closable="!busy"
          :keyboard="!busy"
          @ok="renameBlueprint"
        >
          <div class="blueprint-dialog">
            <label for="blueprint-rename-input">蓝图名称</label>
            <a-input
              id="blueprint-rename-input"
              v-model:value="renameBlueprintDraft"
              :disabled="busy"
              @pressEnter="renameBlueprint"
            />
            <p class="hint">
              支持中文、大小写英文、数字和常用标点，不含空格。改名会保留正文及未保存的编辑。
            </p>
            <a-alert
              v-if="renameBlueprintError"
              type="error"
              show-icon
              :message="renameBlueprintError"
            />
          </div>
        </a-modal>
        <a-modal
          v-model:open="deleteBlueprintOpen"
          title="永久删除蓝图"
          ok-text="永久删除"
          cancel-text="保留蓝图"
          :confirm-loading="busy"
          :ok-button-props="{ danger: true, disabled: busy }"
          :cancel-button-props="{ disabled: busy }"
          :mask-closable="!busy"
          :closable="!busy"
          :keyboard="!busy"
          @ok="deleteBlueprint"
        >
          <div class="blueprint-dialog">
            <div class="blueprint-delete-target">
              <Trash2 :size="20" />
              <div>
                <strong>{{ displayBlueprintName(deleteBlueprintTarget?.name) }}</strong
                ><span>{{ deleteBlueprintTarget?.archived ? '已归档蓝图' : '当前蓝图' }}</span>
              </div>
            </div>
            <p>删除后无法恢复，内容不会进入归档。</p>
            <a-alert
              v-if="
                deleteBlueprintTarget &&
                !deleteBlueprintTarget.archived &&
                blueprintContent !== savedBlueprintContent
              "
              type="warning"
              show-icon
              message="这份蓝图还有未保存的修改，删除后这些修改也会丢失。"
            />
            <a-alert
              v-if="deleteBlueprintError"
              type="error"
              show-icon
              :message="deleteBlueprintError"
            />
          </div>
        </a-modal>

        <section id="topics" v-show="activeSection === 'topics'" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">02</span>
            <div>
              <h2>议题与决策</h2>
              <p>提出问题、审核议题并形成结论</p>
            </div>
          </div>
          <div v-if="topicComposerVisible" class="topic-composer">
            <div class="composer-heading">
              <div>
                <h3>提出新议题</h3>
                <p>用 Markdown 记录背景、目标、方案和待讨论的问题。</p>
              </div>
              <a-button :disabled="busy" @click="topicComposerVisible = false">收起</a-button>
            </div>
            <a-input v-model:value="topicDraftTitle" placeholder="议题标题" />
            <a-textarea
              v-model:value="topicDraftSummary"
              :maxlength="100000"
              :auto-size="{ minRows: 12, maxRows: 32 }"
              placeholder="## 背景\n\n描述问题、现状和影响。\n\n## 目标与方案\n\n列出目标、候选方案和需要讨论的事项。"
            />
            <div class="form-row">
              <a-button
                type="primary"
                :disabled="!topicDraftTitle.trim() || busy"
                @click="submitTopic"
                >创建议题并开始讨论</a-button
              >
              <span class="hint">正文支持 Markdown，单篇最多 100,000 字。</span>
            </div>
          </div>
          <a-alert v-if="topicCommentError" type="error" show-icon :message="topicCommentError" />
          <details v-if="orphanedTopicDraft" class="draft-recovery">
            <summary>复制不可见议题的未提交草稿 · {{ orphanedTopicDraft.title }} · 原修订 {{ orphanedTopicDraft.revision }}</summary>
            <a-textarea :value="`${orphanedTopicDraft.content}\n\n预期：${orphanedTopicDraft.expected}\n核对：${orphanedTopicDraft.conditions}\n原因：${orphanedTopicDraft.reason}`" readonly aria-label="不可见议题草稿" :auto-size="{ minRows: 6, maxRows: 20 }" />
            <a-button @click="orphanedTopicDraft = null">清除此草稿副本</a-button>
          </details>
          <div class="topic-layout">
            <aside class="topic-sidebar">
              <div class="topic-sidebar-heading">
                <strong>议题列表</strong>
                <a-checkbox v-model:checked="showArchivedTopics">显示归档</a-checkbox>
                <span>{{ visibleTopics.length }} / {{ allTopics.length }}</span>
                <a-button size="small" :disabled="busy" @click="topicComposerVisible = true">
                  提出议题
                </a-button>
              </div>
              <a-input v-model:value="topicSearch" aria-label="搜索议题" placeholder="按标题或正文查找" allow-clear />
              <a-select v-model:value="topicFilter" aria-label="议题准入筛选">
                <a-select-option value="all">全部准入状态</a-select-option>
                <a-select-option value="proposed">待纳入</a-select-option>
                <a-select-option value="canonical">已纳入</a-select-option>
                <a-select-option value="rejected">已拒绝</a-select-option>
              </a-select>
              <p v-if="!visibleTopics.length" class="hint topic-list-empty">没有符合条件的议题。</p>
              <article
                v-for="topic in visibleTopics"
                :key="topic.id"
                class="topic-list-card"
                :class="{ active: selectedTopicId === topic.id }"
              >
                <button type="button" class="topic-select" @click="selectTopic(topic)">
                  <span class="topic-list-title">{{ topic.title }}</span>
                  <a-tag :color="governanceStatusColor(topic.admission_status)">{{
                    topicAdmissionLabel(topic.admission_status)
                  }}</a-tag>
                  <span class="topic-list-summary">{{ topic.summary || '暂无议题说明' }}</span>
                </button>
                <a-tag>{{ topicProgressLabel(topic.progress) }}</a-tag>
                <a-tag v-if="topic.requires_review" color="orange">需复核</a-tag>
                <a-button
                  v-if="!topic.archived_at"
                  size="small"
                  :disabled="busy"
                  @click="createDecisionFromTopic(topic)"
                  >新增决策</a-button
                >
              </article>
            </aside>

            <div v-if="selectedTopic" class="topic-detail">
              <header class="topic-detail-heading">
                <div>
                  <p class="eyebrow">议题详情</p>
                  <h3>{{ selectedTopic.title }}</h3>
                  <a-tag :color="governanceStatusColor(selectedTopic.admission_status)">{{
                    topicAdmissionLabel(selectedTopic.admission_status)
                  }}</a-tag>
                  <a-tag>{{ topicProgressLabel(selectedTopic.progress) }}</a-tag>
                  <a-tag v-if="selectedTopic.archived_at">已归档</a-tag>
                </div>
                <a-button
                  v-if="!selectedTopic.archived_at && !editingTopic"
                  :disabled="busy"
                  @click="beginEditTopic"
                  >修改提议</a-button
                >
              </header>

              <div v-if="editingTopic" class="topic-editor">
                <a-alert v-if="topicEditError" type="error" show-icon :message="topicEditError" />
                <a-input v-model:value="editingTopicTitle" aria-label="议题标题" />
                <a-textarea
                  v-model:value="editingTopicSummary"
                  :maxlength="100000"
                  :auto-size="{ minRows: 16, maxRows: 36 }"
                  placeholder="使用 Markdown 编辑议题正文"
                />
                <a-textarea v-model:value="editingTopicExpected" aria-label="预期结果" placeholder="预期结果（可选）" :maxlength="100000" />
                <a-textarea v-model:value="editingTopicConditions" aria-label="核对条件" placeholder="核对条件（可选）" :maxlength="100000" />
                <a-input
                  v-model:value="editingTopicReason"
                  placeholder="修改原因（必填）"
                  aria-label="议题修改原因"
                />
                <div class="form-row">
                  <a-button
                    type="primary"
                    :disabled="!editingTopicTitle.trim() || !editingTopicReason.trim() || busy"
                    @click="saveTopicEdit"
                    >保存议题修改</a-button
                  >
                  <a-button :disabled="busy" @click="cancelTopicEdit">取消</a-button>
                </div>
              </div>
              <section v-else class="topic-proposal-body">
                <MarkdownPreview v-if="selectedTopic.summary" :content="selectedTopic.summary" />
                <p v-else class="hint">
                  暂无议题说明。{{
                    selectedTopic.admission_status === 'proposed'
                      ? '可以先修改提议，补充背景和方案。'
                      : ''
                  }}
                </p>
              </section>

              <section v-if="!editingTopic" class="current-topic-context" aria-label="当前决定与关联工作">
                <h4>当前有效决定</h4>
                <p v-if="!selectedTopicDecisions.length" class="hint">尚无已批准决定；讨论和工作可独立进行。</p>
                <article v-for="decision in selectedTopicDecisions" :key="decision.id" class="context-card">
                  <button type="button" class="context-link" @click="selectDecision(decision.id)">{{ decision.title }} · 修订 {{ decision.revision_number }}</button>
                  <a-tag v-if="decision.requires_review" color="orange">需复核</a-tag>
                  <MarkdownPreview :content="decision.conclusion || ''" />
                  <RouterLink :to="decisionWorkLink(decision)">基于此决定创建正式工作</RouterLink>
                </article>
                <h4>关联工作与建议</h4>
                <RouterLink v-for="work in selectedTopicWorks" :key="work.id" class="context-card" :to="{ name: 'ProjectWorkTaskView', params: { project_id: projectId, task_id: work.id } }">{{ work.number }} · {{ work.title }} · {{ overviewStatusLabel(work.status) }}</RouterLink>
                <p v-if="!selectedTopicSuggestions.length && !selectedTopicWorks.length" class="hint">当前没有关联工作建议；正式工作仍可从项目“工作”独立创建。</p>
                <div v-for="item in selectedTopicSuggestions" :key="item.id" class="context-card">
                  <RouterLink v-if="item.work" :to="{ name: 'ProjectWorkTaskView', params: { project_id: projectId, task_id: item.work.id } }">建议 {{ item.title }} · 已纳入 {{ item.work.number }}</RouterLink>
                  <button v-else type="button" class="context-link" @click="openSuggestion(item)">{{ item.title }} · {{ governanceStatusLabel(item.status) }}</button>
                </div>
              </section>

              <TopicHistoryPanel
                :key="`${projectId}:${selectedTopic.id}`"
                :project-id="projectId"
                :topic="selectedTopic"
                :draft="topicDiscussionDraft(selectedTopic.id)"
                :decisions="board.governance?.decisions || []"
                @updated="load"
                @visibility-lost="visibilityLost"
              />

              <footer
                v-if="
                  selectedTopic.admission_status === 'proposed' &&
                  !selectedTopic.archived_at &&
                  !editingTopic
                "
                class="topic-review-actions"
              >
                <div>
                  <strong>纳入审核</strong>
                  <p>纳入后仍可修改和研讨；纳入不代表批准决策。</p>
                </div>
                <div class="form-row">
                  <a-button danger :disabled="busy" @click="reviewTopic(selectedTopic, false)"
                    >拒绝提议</a-button
                  >
                  <a-button
                    type="primary"
                    :disabled="busy"
                    @click="reviewTopic(selectedTopic, true)"
                  >
                    通过纳入
                  </a-button>
                </div>
              </footer>
              <p v-else-if="selectedTopic.review?.reviewed_at" class="hint topic-review-note">
                {{ selectedTopic.admission_status === 'canonical' ? '已通过' : '已拒绝' }} ·
                {{ timestampLabel(selectedTopic.review.reviewed_at) }}
                <span v-if="selectedTopic.review.note"> · {{ selectedTopic.review.note }}</span>
              </p>
            </div>
            <div v-else class="topic-detail-empty">
              <MessagesSquare :size="28" />
              <strong>选择一个议题查看详情</strong>
              <p>议题正文、讨论和审核操作会显示在这里。</p>
              <a-button type="primary" @click="topicComposerVisible = true"
                >提出第一个议题</a-button
              >
            </div>
          </div>

          <details id="decision-entry" :open="decisionComposerVisible" class="decision-entry" @toggle="decisionComposerVisible = $event.target.open">
            <summary>新增决策草案</summary>
            <div class="composer-heading">
              <div>
                <h3>新增决策</h3>
                <p>新增默认保存为草案；批准需显式操作，不自动确认议题或控制执行。</p>
              </div>
              <a-tag v-if="decisionTopicId">已关联议题</a-tag>
            </div>
            <div class="form-row">
              <a-input v-model:value="decisionTitle" placeholder="决策标题" />
              <a-select
                v-model:value="decisionTopicId"
                allow-clear
                placeholder="关联议题"
                style="min-width: 220px"
              >
                <a-select-option
                  v-for="topic in selectableTopics"
                  :key="topic.id"
                  :value="topic.id"
                >
                  {{ topic.title }}
                </a-select-option>
              </a-select>
            </div>
            <div class="form-row">
              <a-select
                v-model:value="decisionRelationType"
                aria-label="决策形成方式"
                @change="decisionTargetId = undefined"
              >
                <a-select-option value="ordinary">普通决策</a-select-option>
                <a-select-option value="supplement">补充决策</a-select-option>
                <a-select-option value="replacement">整条替代</a-select-option>
              </a-select>
              <a-select
                v-if="decisionRelationType !== 'ordinary'"
                v-model:value="decisionTargetId"
                aria-label="目标决策"
                placeholder="选择当前有效的目标决策"
                style="min-width: 220px"
              >
                <a-select-option
                  v-for="target in (board.governance?.decisions || []).filter(
                    (d) => d.status === 'approved'
                  )"
                  :key="target.id"
                  :value="target.id"
                  >{{ target.title }}</a-select-option
                >
              </a-select>
            </div>
            <p v-if="decisionRelationType !== 'ordinary' && !decisionTargetId" class="hint">
              请选择补充或整条替代的目标决策。
            </p>
            <a-textarea
              v-model:value="decisionConclusion"
              :auto-size="{ minRows: 8, maxRows: 24 }"
              placeholder="明确结论与执行方向，支持 Markdown。"
            />
            <a-textarea
              v-model:value="decisionRationale"
              :auto-size="{ minRows: 6, maxRows: 20 }"
              placeholder="决策理由、依据、风险与被否替代方案。"
            />
            <div class="form-row">
              <a-button
                type="primary"
                :disabled="
                  !decisionTitle.trim() ||
                  !decisionConclusion.trim() ||
                  busy ||
                  (decisionRelationType !== 'ordinary' && !decisionTargetId)
                "
                @click="createDecision"
                >保存决策草案</a-button
              >
            </div>
          </details>
          <section id="decisions" class="decision-records">
            <div class="composer-heading">
              <div>
                <h3>已有决策</h3>
                <p>决策记录保留结论、理由和关联议题。</p>
              </div>
              <span class="hint">{{ board.governance?.decisions?.length || 0 }} 条</span>
            </div>
            <p v-if="!board.governance?.decisions?.length" class="hint">还没有决策记录。</p>
            <DecisionHistoryPanel
              :project-id="projectId"
              :decisions="board.governance?.decisions || []"
              :topics="allTopics"
              :selected-id="String(route.query.decision_id || '')"
              @updated="load"
                @visibility-lost="visibilityLost"
              @select="selectDecision"
              @compose="composeRelatedDecision"
              @topic="openDecisionTopic"
            />
          </section>
        </section>

        <section id="tasks" v-show="activeSection === 'tasks'" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">03</span>
            <div>
              <h2>工作建议与历史执行</h2>
              <p>建议纳入正式工作后执行，旧执行记录继续保留。</p>
            </div>
          </div>
          <details :open="taskComposerVisible" class="suggestion-composer" @toggle="taskComposerVisible = $event.target.open">
            <summary>记录工作建议</summary>
            <p class="hint">议题、决定和数字员工均可不选；直接创建正式工作请进入项目“工作”。</p>
          <div class="form-row">
            <a-input v-model:value="taskTitle" placeholder="工作建议标题" /><a-select
              v-model:value="taskAgentSlug"
              allow-clear
              placeholder="项目数字员工"
              style="min-width: 180px"
              ><a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{
                agent.name || agent.slug
              }}</a-select-option></a-select
            >
          </div>
          <a-textarea
            v-model:value="taskDescription"
            :rows="3"
            placeholder="交付物、验收条件和工作范围"
          />
          <div class="form-row">
            <a-select
              v-model:value="taskTopicId"
              allow-clear
              placeholder="关联议题"
              style="min-width: 180px"
            >
              <a-select-option v-for="topic in selectableTopics" :key="topic.id" :value="topic.id">
                {{ topic.title }}
              </a-select-option>
            </a-select>
            <a-select
              v-model:value="taskDecisionId"
              allow-clear
              placeholder="关联决策"
              style="min-width: 180px"
              ><a-select-option
                v-for="decision in board.governance?.decisions || []"
                :key="decision.id"
                :value="decision.id"
                >{{ decision.title }}</a-select-option
              ></a-select
            ><a-button :disabled="!taskTitle.trim() || busy" @click="createTask"
              >创建工作建议</a-button
            >
          </div>
          </details>
          <WorkSuggestionsPanel :project-id="projectId" :suggestions="board.governance?.tasks || []" :topics="allTopics" :decisions="board.governance?.decisions || []" @reject="task => reviewTask(task, false)" @admitted="load" @visibility-lost="visibilityLost" />
          <ul class="workbench-list">
            <li
              v-for="task in (board.governance?.tasks || []).filter(item => taskDelegations(item.id).length)"
              :id="`legacy-execution-${task.id}`"
              :key="task.id"
              :class="{ 'selected-governance-item': route.query.task_id === task.id }"
            >
              <strong>{{ task.title }}</strong
              ><a-tag :color="governanceStatusColor(task.status)">{{
                governanceStatusLabel(task.status)
              }}</a-tag
              ><span>{{ task.assignee_agent_slug || '未指派' }}</span>
              <span>历史执行记录</span>
              <ul v-if="taskDelegations(task.id).length" class="delegation-list">
                <li v-for="item in taskDelegations(task.id)" :key="item.operation_id">
                  {{ item.executor_key }} · {{ delegationStatusLabel(item) }}
                  <span v-if="item.error_code"> · {{ item.error_code }}</span>
                  <span v-if="item.remote_status === 'failed'"> · 执行会话失败</span>
                  <a-button
                    v-if="item.dispatch_state === 'dispatched'"
                    size="small"
                    :disabled="busy"
                    @click="refreshDelegation(item)"
                    >查状态</a-button
                  >
                  <a-button
                    v-if="item.dispatch_state === 'dispatched' && terminalTurn(item.remote_status)"
                    size="small"
                    :disabled="busy"
                    @click="collectDelegation(item)"
                    >回收</a-button
                  >
                  <p v-if="item.result?.summary">{{ item.result.summary }}</p>
                  <p v-if="item.artifact_path">产物：{{ item.artifact_path }}</p>
                  <a-button
                    v-if="item.session_id"
                    type="link"
                    size="small"
                    @click="showSession(item)"
                    >查看执行详情</a-button
                  >
                  <p v-if="sessionDetails[item.session_id]" class="delegation-detail">
                    会话 {{ item.session_id }} · {{ sessionDetails[item.session_id].status }}
                    <span v-if="sessionDetails[item.session_id].error_code">
                      · {{ sessionDetails[item.session_id].error_code }}</span
                    >
                    <span v-if="sessionDetails[item.session_id].error_message">
                      · {{ sessionDetails[item.session_id].error_message }}</span
                    >
                  </p>
                </li>
              </ul>
            </li>
          </ul>
        </section>

        <section id="reports" v-show="activeSection === 'reports'" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">04</span>
            <div>
              <h2>督查与汇报</h2>
              <p>查看待处理事项、阻塞执行和项目汇报</p>
            </div>
          </div>
          <GovernanceBoardPanel :board="board" />
          <ul class="workbench-list">
            <li v-for="report in board.governance?.reports || []" :key="report.id">
              <strong>{{ report.title }}</strong
              ><span>{{ report.summary }}</span
              ><span v-if="report.artifact_path">{{ report.artifact_path }}</span>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useReturnScroll } from '@/utils/pageReturnScroll'
import { blueprintTemplates, blueprintTemplateContent } from '@/utils/blueprintTemplates'
import TopicHistoryPanel from '@/components/project/TopicHistoryPanel.vue'
import DecisionHistoryPanel from '@/components/project/DecisionHistoryPanel.vue'
import { topicAdmissionLabel, topicProgressLabel } from '@/utils/governanceBoard'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import WorkSuggestionsPanel from '@/components/project/WorkSuggestionsPanel.vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { MessagesSquare, Ellipsis, Pencil, Archive, Trash2 } from '@lucide/vue'
import { codingSessionApi } from '@/apis/coding_session_api'
import GovernanceBoardPanel from '@/components/inspection/GovernanceBoardPanel.vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { displayBlueprintName, normalizeBlueprintName } from '@/utils/blueprintName'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { useUserStore } from '@/stores/user'
import { getGovernanceDraft, setGovernanceDraft, clearGovernanceDrafts } from '@/utils/governanceDrafts'
import { projectWorkApi } from '@/apis/project_work_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import {
  describeBoardError,
  governanceStatusColor,
  governanceStatusLabel,
  overviewStatusLabel
} from '@/utils/governanceBoard'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
let active = true
const projectId = computed(() => String(route.params.project_id || ''))
const loading = ref(false)
const scrollContainer = ref(null)
useReturnScroll(loading, () => scrollContainer.value)
const busy = ref(false)
const errorMessage = ref('')
const actionError = ref('')
const board = ref({ project: null, governance: null, execution: null })
const blueprints = ref([])
const blueprintName = ref('')
const newBlueprintName = ref('')
const createBlueprintOpen = ref(false)
const createBlueprintError = ref('')
const newBlueprintTemplate = ref('blank')
const newBlueprintContent = ref('')
const newBlueprintBaseline = ref('')
const blueprintProjectType = ref('unspecified')
const sharedBlueprintDirectory = ref(false)
let newBlueprintInitialized = false
const blueprintActionError = ref('')
const blueprintContent = ref('')
const blueprintEditing = ref(false)
const activeSection = ref('blueprint')
const loadedBlueprintName = ref('')
const savedBlueprintContent = ref('')
const renameBlueprintOpen = ref(false)
const renameBlueprintDraft = ref('')
const renameBlueprintError = ref('')
const deleteBlueprintOpen = ref(false)
const deleteBlueprintTarget = ref(null)
const deleteBlueprintError = ref('')
const archivedBlueprints = ref([])
const selectedArchive = ref('')
const archiveContent = ref('')
const archiveError = ref('')
const archiveLoading = ref(false)
const agents = ref([])
const delegations = ref([])
const topicComposerVisible = ref(false)
const topicDraftTitle = ref('')
const topicDraftSummary = ref('')
const selectedTopicId = ref('')
const topicEditError = ref('')
const orphanedTopicDraft = ref(null)
const topicDiscussionDrafts = ref({})
// 草稿由工作台按议题保留，切换详情不会丢失未发送内容。
function topicDiscussionDraft(topicId) {
  topicDiscussionDrafts.value[topicId] ||= { content: '', discussionType: 'discussion' }
  return topicDiscussionDrafts.value[topicId]
}
const topicCommentError = ref('')
const editingTopic = ref(false)
const editingTopicId = ref('')
const editingTopicTitle = ref('')
const editingTopicSummary = ref('')
const editingTopicExpected = ref('')
const editingTopicConditions = ref('')
const decisionTitle = ref('')
const decisionConclusion = ref('')
const decisionRationale = ref('')
const decisionTopicId = ref(undefined)
const decisionRelationType = ref('ordinary')
const decisionTargetId = ref(undefined)
const taskTitle = ref('')
const taskDescription = ref('')
const taskTopicId = ref(undefined)
const taskDecisionId = ref(undefined)
const taskAgentSlug = ref(undefined)
const sessionDetails = ref({})
const sectionLinks = [
  { id: 'blueprint', label: '项目蓝图' },
  { id: 'topics', label: '议题与决策' },
  { id: 'tasks', label: '工作建议' },
  { id: 'reports', label: '督查与汇报' }
]
/** 旧对象锚点先展开所属栏目，再定位原对象。 */
async function jumpTo(id) {
  if (!active) return
  const section = sectionLinks.some(item => item.id === id) ? id
    : id.startsWith('task-') || id.startsWith('legacy-execution-') ? 'tasks'
    : id.startsWith('decision-') || id === 'decisions' ? 'topics' : null
  if (section) activeSection.value = section
  if (id === 'decision-entry') decisionComposerVisible.value = true
  await nextTick()
  if (!active) return
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
let blueprintReadSeq = 0
let archiveReadSeq = 0
let loadSeq = 0
const pageTitle = computed(() =>
  board.value?.project?.name ? `${board.value.project.name} · 项目工作台` : '项目工作台'
)
const formalWorks = ref([])
const topicRows = ref([])
const topicSearch = ref('')
const topicFilter = ref('all')
const decisionComposerVisible = ref(false)
const taskComposerVisible = ref(false)
const showArchivedTopics = ref(false)
const allTopics = computed(() => topicRows.value)
const visibleTopics = computed(() =>
  allTopics.value.filter((t) => (showArchivedTopics.value || !t.archived_at) && (topicFilter.value === 'all' || t.admission_status === topicFilter.value) && `${t.title} ${t.summary || ''}`.toLocaleLowerCase().includes(topicSearch.value.trim().toLocaleLowerCase()))
)
const selectableTopics = computed(() => allTopics.value.filter((t) => !t.archived_at))
const selectedTopicDecisions = computed(() => (board.value.governance?.decisions || []).filter(d => d.topic_id === selectedTopicId.value && d.status === 'approved'))
const selectedTopicWorks = computed(() => formalWorks.value.filter(w => w.topic_id === selectedTopicId.value || selectedTopicDecisions.value.some(d => d.id === w.source_decision_id)))
const selectedTopicSuggestions = computed(() => (board.value.governance?.tasks || []).filter(t => t.topic_id === selectedTopicId.value || selectedTopicDecisions.value.some(d => d.id === t.decision_id)))
const decisionWorkLink = decision => ({ name: 'ProjectWorkTasksView', params: { project_id: projectId.value }, query: { create: '1', source_decision_id: decision.id, ...(decision.topic_id ? { topic_id: decision.topic_id } : {}) } })
function openSuggestion(item) { router.replace({ query: { ...route.query, task_id: item.id }, hash: `#task-${item.id}` }); jumpTo(`task-${item.id}`) }
function navigateSection(id) { router.replace({ query: route.query, hash: `#${id}` }); jumpTo(id) }
const editingTopicReason = ref('')
const editingTopicRevision = ref(null)
// 只缓存表单及其原依据，不缓存后端状态、权限或业务读投影。
const formRefs = { topicSearch, topicFilter, showArchivedTopics, decisionComposerVisible, taskComposerVisible, activeSection, blueprintEditing, blueprintName, loadedBlueprintName,
  blueprintContent, savedBlueprintContent, newBlueprintName, newBlueprintContent,
  newBlueprintTemplate, newBlueprintBaseline, topicDraftTitle, topicDraftSummary,
  topicComposerVisible, orphanedTopicDraft, topicDiscussionDrafts, selectedTopicId, editingTopic, editingTopicId,
  editingTopicTitle, editingTopicSummary, editingTopicExpected, editingTopicConditions,
  editingTopicReason, editingTopicRevision, decisionTitle, decisionConclusion,
  decisionRationale, decisionTopicId, decisionRelationType, decisionTargetId,
  taskTitle, taskDescription, taskTopicId, taskDecisionId, taskAgentSlug }
const copy = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value))
const formDefaults = Object.fromEntries(Object.entries(formRefs).map(([name, value]) => [name, copy(value.value)]))
let draftScope = { user: user.uid, project: projectId.value }
let restoringForms = false
function restoreForms() {
  const draft = getGovernanceDraft(user.uid, projectId.value, 'workbench')
  restoringForms = true
  for (const [name, value] of Object.entries(formRefs)) value.value = copy(draft?.[name] ?? formDefaults[name])
  newBlueprintInitialized = Boolean(newBlueprintContent.value)
  restoringForms = false
}
async function visibilityLost(error) {
  const status = error?.status || error?.response?.status
  const project = projectId.value, owner = user.uid
  if (status === 404) {
    try {
      await api.getProjectBoard(project)
      return // 单个对象不可见，保留原对象草稿供核对，不清同项目其他正文。
    } catch (failure) {
      if (![401, 403, 404].includes(failure?.status || failure?.response?.status)) return
    }
  }
  if (project !== projectId.value || owner !== user.uid) return
  errorMessage.value = describeBoardError(error)
  clearGovernanceDrafts(user.uid, projectId.value)
  restoreForms()
}
function persistForms() {
  if (restoringForms || errorMessage.value || draftScope.user !== user.uid || draftScope.project !== projectId.value) return
  setGovernanceDraft(user.uid, projectId.value, 'workbench',
    Object.fromEntries(Object.entries(formRefs).map(([name, value]) => [name, value.value])))
}
watch(Object.values(formRefs), persistForms, { deep: true, flush: 'sync' })
const selectedTopic = computed(() =>
  allTopics.value.find((item) => item.id === selectedTopicId.value)
)
const taskDelegations = (taskId) =>
  delegations.value.filter((item) => item.governance_task_id === taskId)
const delegationStatusLabel = (item) =>
  ({
    queued: '等待派发',
    dispatching: '派发中',
    dispatched: '已派发',
    reclaimed: '已回收',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消'
  })[item.remote_status || item.dispatch_state] ||
  item.remote_status ||
  item.dispatch_state
const terminalTurn = (status) =>
  ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
const archiveTimeLabel = (raw) => {
  const value = String(raw || '')
  if (!/^\d{8}T\d{12}Z$/.test(value)) return value
  const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T${value.slice(9, 11)}:${value.slice(11, 13)}:${value.slice(13, 15)}.${value.slice(15, 18)}Z`
  return new Date(iso).toLocaleString('zh-CN')
}
const timestampLabel = (raw) => {
  if (!raw) return ''
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? String(raw) : date.toLocaleString('zh-CN')
}

async function readBlueprint() {
  if (!blueprintName.value) return
  if (loadedBlueprintName.value && blueprintContent.value !== savedBlueprintContent.value) {
    blueprintName.value = loadedBlueprintName.value
    blueprintActionError.value = '蓝图有未保存的修改，请先保存后切换文档'
    return
  }
  const name = blueprintName.value
  const project = projectId.value
  const owner = user.uid
  const before = blueprintContent.value
  const seq = ++blueprintReadSeq
  try {
    const document = await api.getBlueprint(project, name)
    if (seq !== blueprintReadSeq || blueprintName.value !== name || projectId.value !== project || owner !== user.uid)
      return
    if (blueprintContent.value !== before) return
    blueprintContent.value = document.content
    savedBlueprintContent.value = document.content
    loadedBlueprintName.value = document.name
  } catch (error) {
    if (seq !== blueprintReadSeq || blueprintName.value !== name || projectId.value !== project || owner !== user.uid)
      return
    blueprintName.value = loadedBlueprintName.value
    blueprintActionError.value = describeBoardError(error)
  }
}

async function readArchive(name) {
  const project = projectId.value
  const owner = user.uid
  const seq = ++archiveReadSeq
  selectedArchive.value = name
  archiveLoading.value = true
  archiveError.value = ''
  archiveContent.value = ''
  try {
    const document = await api.getBlueprintArchive(project, name)
    if (seq !== archiveReadSeq || projectId.value !== project || owner !== user.uid) return
    archiveContent.value = document.content
  } catch (error) {
    if (seq !== archiveReadSeq || projectId.value !== project || owner !== user.uid) return
    archiveError.value = describeBoardError(error)
  } finally {
    if (seq === archiveReadSeq && projectId.value === project && owner === user.uid) archiveLoading.value = false
  }
}

function setTopicRoute(topicId) {
  const query = { ...route.query }
  if (topicId) query.topic_id = topicId
  else delete query.topic_id
  delete query.task_id
  delete query.decision_id
  delete query.decision_revision
  if (topicId !== route.query.topic_id) {
    delete query.comment_id
    delete query.revision
  }
  router.replace({
    name: 'ProjectInspectionBoardComp',
    params: { project_id: projectId.value },
    query,
    hash: '#topics'
  })
}

function selectTopic(topic) {
  if (!canLeaveTopicEditor()) return
  selectedTopicId.value = topic.id
  editingTopic.value = false
  topicCommentError.value = ''
  setTopicRoute(topic.id)
}

function selectDecision(id) {
  const query = { ...route.query }
  if (id !== route.query.decision_id) delete query.decision_revision
  if (id) query.decision_id = id
  else delete query.decision_id
  activeSection.value = 'topics'
  router.replace({ query, hash: '#decisions' })
}
function openDecisionTopic(id) {
  const topic = allTopics.value.find((t) => t.id === id)
  if (topic) selectTopic(topic)
}
function composeRelatedDecision(decision, relationType) {
  if (decisionTitle.value || decisionConclusion.value || decisionRationale.value) {
    actionError.value = '已有未提交的决策草案，请先保存；原草稿与来源保持不变。'
    jumpTo('decision-entry')
    return
  }
  decisionTitle.value = ''
  decisionConclusion.value = ''
  decisionRationale.value = ''
  decisionTopicId.value = decision.topic_id || undefined
  decisionRelationType.value = relationType
  decisionTargetId.value = decision.id
  nextTick(() => jumpTo('decision-entry'))
}

function createDecisionFromTopic(topic) {
  if (decisionTitle.value || decisionConclusion.value || decisionRationale.value) {
    actionError.value = '已有未提交的决策草案，请先保存；原草稿与来源保持不变。'
    jumpTo('decision-entry')
    return
  }
  if (!canLeaveTopicEditor()) return
  selectedTopicId.value = topic.id
  decisionTopicId.value = topic.id
  decisionRelationType.value = 'ordinary'
  decisionTargetId.value = undefined
  decisionTitle.value = topic.title
  decisionConclusion.value = ''
  decisionRationale.value = ''
  setTopicRoute(topic.id)
  nextTick(() => jumpTo('decision-entry'))
}

function canLeaveTopicEditor() {
  if (
    !editingTopic.value ||
    !selectedTopic.value ||
    (editingTopicTitle.value === selectedTopic.value.title &&
      editingTopicSummary.value === (selectedTopic.value.summary || '') &&
      editingTopicExpected.value === (selectedTopic.value.expected_outcome || '') &&
      editingTopicConditions.value === (selectedTopic.value.verification_conditions || ''))
  )
    return true
  topicCommentError.value = '当前提议有未保存的修改，请先保存或取消编辑。'
  return false
}

const topicEditFields = { editingTopicTitle, editingTopicSummary, editingTopicExpected, editingTopicConditions, editingTopicReason, editingTopicRevision }
watch(Object.values(topicEditFields), () => {
  if (editingTopic.value && editingTopicId.value && !restoringForms && draftScope.user === user.uid && draftScope.project === projectId.value)
    setGovernanceDraft(user.uid, projectId.value, `topic-edit:${editingTopicId.value}`, Object.fromEntries(Object.entries(topicEditFields).map(([name, value]) => [name, value.value])))
}, { deep: true, flush: 'sync' })
function cancelTopicEdit() {
  setGovernanceDraft(user.uid, projectId.value, `topic-edit:${editingTopicId.value}`, null)
  editingTopic.value = false
}
function beginEditTopic() {
  if (!selectedTopic.value || selectedTopic.value.archived_at) return
  topicEditError.value = ''
  editingTopicId.value = selectedTopic.value.id
  editingTopicTitle.value = selectedTopic.value.title
  editingTopicSummary.value = selectedTopic.value.summary || ''
  editingTopicExpected.value = selectedTopic.value.expected_outcome || ''
  editingTopicConditions.value = selectedTopic.value.verification_conditions || ''
  editingTopicReason.value = ''
  editingTopicRevision.value = selectedTopic.value.revision_number
  const saved = getGovernanceDraft(user.uid, projectId.value, `topic-edit:${editingTopicId.value}`)
  if (saved) {
    restoringForms = true
    for (const [name, value] of Object.entries(topicEditFields)) value.value = saved[name]
    restoringForms = false
    if (editingTopicRevision.value !== selectedTopic.value.revision_number) topicEditError.value = '草稿保留原修订，请先核对当前正文；不会自动改换依据重放。'
  }
  editingTopic.value = true
}

async function load() {
  const project = projectId.value
  const owner = user.uid
  const seq = ++loadSeq
  loading.value = true
  errorMessage.value = ''
  try {
    const [boardResult, docsResult, archiveResult, agentResult, delegationResult, topicsResult, worksResult] =
      await Promise.allSettled([
        api.getProjectBoard(project),
        api.listBlueprints(project),
        api.listBlueprintArchives(project),
        projectAgentApi.list(project),
        api.listDelegations(project),
        api.listTopics(project, true),
        projectWorkApi.listTasks(project)
      ])
    if (seq !== loadSeq || projectId.value !== project || owner !== user.uid) return
    if (boardResult.status === 'rejected') throw boardResult.reason
    board.value = boardResult.value
    formalWorks.value = worksResult.status === 'fulfilled' ? worksResult.value : []
    topicRows.value =
      topicsResult.status === 'fulfilled'
        ? topicsResult.value
        : boardResult.value.governance?.topics || []
    const topics = topicRows.value
    const requestedTopicId = String(route.query.topic_id || '')
    const missingTopic = topicsResult.status === 'fulfilled' && ((requestedTopicId && !topics.some(item => item.id === requestedTopicId)) || (editingTopic.value && selectedTopicId.value && !topics.some(item => item.id === selectedTopicId.value)))
    if (missingTopic) {
      if (editingTopic.value) orphanedTopicDraft.value = { id: selectedTopicId.value, revision: editingTopicRevision.value, title: editingTopicTitle.value, content: editingTopicSummary.value, expected: editingTopicExpected.value, conditions: editingTopicConditions.value, reason: editingTopicReason.value }
      editingTopic.value = false
      topicCommentError.value = '原议题不可见或已移除，不会把原草稿提交到另一议题。请核对原地址；未提交正文仍保留供复制。'
    }
    const nextTopic = missingTopic ? null :
      topics.find((item) => item.id === requestedTopicId) ||
      topics.find((item) => item.id === selectedTopicId.value) ||
      [...topics]
        .reverse()
        .find((item) => item.admission_status === 'proposed' && !item.archived_at) ||
      [...topics].reverse()[0]
    if (editingTopic.value && nextTopic?.id !== editingTopicId.value) editingTopic.value = false
    selectedTopicId.value = nextTopic?.id || ''

    agents.value = agentResult.status === 'fulfilled' ? agentResult.value.agents || [] : []
    delegations.value = delegationResult.status === 'fulfilled' ? delegationResult.value : []
    const auxiliaryErrors = [docsResult, archiveResult, agentResult, delegationResult, topicsResult, worksResult]
      .filter((result) => result.status === 'rejected')
      .map((result) => describeBoardError(result.reason))
    if (auxiliaryErrors.length)
      actionError.value = `部分工作台数据加载失败：${auxiliaryErrors.join('；')}`
    if (archiveResult.status === 'fulfilled')
      archivedBlueprints.value = archiveResult.value.documents || []
    if (docsResult.status === 'fulfilled') {
      blueprints.value = docsResult.value.documents || []
      blueprintProjectType.value = docsResult.value.project_type || 'unspecified'
      sharedBlueprintDirectory.value = Boolean(docsResult.value.shared_workdir)
      if (!blueprintName.value && blueprints.value.length)
        blueprintName.value = blueprints.value[0].name
      if (blueprintName.value && blueprintContent.value === savedBlueprintContent.value) {
        if (blueprints.value.some((doc) => doc.name === blueprintName.value)) await readBlueprint()
        else {
          blueprintName.value = blueprints.value[0]?.name || ''
          if (blueprintName.value) await readBlueprint()
        }
      }
      if (!blueprints.value.length) {
        if (blueprintContent.value !== savedBlueprintContent.value) {
          blueprintActionError.value = '原蓝图已不在当前列表，未保存草稿保留供复制；请核对后新建。'
        } else {
          blueprintName.value = ''
          loadedBlueprintName.value = ''
          blueprintContent.value = ''
          savedBlueprintContent.value = ''
        }
      }
    }
  } catch (error) {
    if (seq === loadSeq && projectId.value === project && owner === user.uid) {
      errorMessage.value = describeBoardError(error)
      if ([401, 403, 404].includes(error?.status || error?.response?.status)) {
        clearGovernanceDrafts(user.uid, project)
        restoreForms()
      }
    }
  } finally {
    if (seq === loadSeq && projectId.value === project && owner === user.uid) loading.value = false
  }
}

async function act(operation, errorTarget = actionError) {
  const project = projectId.value, owner = user.uid
  busy.value = true
  errorTarget.value = ''
  try {
    await operation(() => project === projectId.value && owner === user.uid)
    if (project !== projectId.value || owner !== user.uid) return
    await load()
  } catch (error) {
    if (project !== projectId.value || owner !== user.uid) return
    errorTarget.value = describeBoardError(error)
    if ([401, 403, 404].includes(error?.status || error?.response?.status)) await visibilityLost(error)
    if (error?.response?.data?.detail?.code === 'revision_conflict') {
      errorTarget.value += '。您的草稿已保留，可先复制正文，再取消编辑并刷新后重新修改。'
    }
  } finally {
    if (project === projectId.value && owner === user.uid) busy.value = false
  }
}

/** 新建使用独立草稿，已有编辑先保存，取消不写文件。 */
function openCreateBlueprint() {
  if (loadedBlueprintName.value && blueprintContent.value !== savedBlueprintContent.value) {
    blueprintActionError.value = '蓝图有未保存的修改，请先保存后新建文档'
    return
  }
  if (!newBlueprintInitialized) {
    newBlueprintTemplate.value = blueprintProjectType.value === 'unspecified' ? 'blank' : blueprintProjectType.value
    newBlueprintContent.value = blueprintTemplateContent(newBlueprintTemplate.value)
    newBlueprintBaseline.value = newBlueprintContent.value
    newBlueprintInitialized = true
  }
  createBlueprintError.value = ''
  createBlueprintOpen.value = true
}

/** 覆盖已编辑正文前确认，取消保持原模板与草稿。 */
function changeBlueprintTemplate(type) {
  if (type === newBlueprintTemplate.value) return
  const project = projectId.value
  const owner = user.uid
  const apply = () => {
    if (project !== projectId.value || owner !== user.uid || !createBlueprintOpen.value) return
    newBlueprintTemplate.value = type
    newBlueprintContent.value = blueprintTemplateContent(type)
    newBlueprintBaseline.value = newBlueprintContent.value
  }
  if (newBlueprintContent.value !== newBlueprintBaseline.value) {
    Modal.confirm({ title: '替换蓝图草稿？', content: '切换模板会替换当前正文。取消可保留已编辑内容。', okText: '替换正文', cancelText: '保留草稿', onOk: apply })
  } else apply()
}

/** 独占创建并回读正文，失败保留弹窗输入。 */
async function createBlueprint() {
  if (busy.value) return
  if (loadedBlueprintName.value && blueprintContent.value !== savedBlueprintContent.value) {
    createBlueprintError.value = '当前蓝图有未保存修改，请先保存'
    return
  }
  const name = normalizeBlueprintName(newBlueprintName.value.trim())
  if (!name) {
    createBlueprintError.value = '名称需以中文、英文或数字开头，可含常用标点，不含空格且不超过 120 字；中文较多时请适当缩短'
    return
  }
  const project = projectId.value
  const owner = user.uid
  busy.value = true
  createBlueprintError.value = ''
  try {
    const created = await api.createBlueprint(project, name, newBlueprintContent.value)
    if (project !== projectId.value || owner !== user.uid) return
    blueprintReadSeq += 1
    blueprintName.value = created.name
    loadedBlueprintName.value = created.name
    blueprintContent.value = created.content
    savedBlueprintContent.value = created.content
    createBlueprintOpen.value = false
    newBlueprintInitialized = false
    newBlueprintName.value = ''
    newBlueprintContent.value = ''
    await load()
  } catch (error) {
    if (project === projectId.value && owner === user.uid) createBlueprintError.value = describeBoardError(error)
    if (project === projectId.value && owner === user.uid && [401, 403, 404].includes(error?.status || error?.response?.status)) await visibilityLost(error)
  } finally {
    if (project === projectId.value && owner === user.uid) busy.value = false
  }
}
const saveBlueprint = () => {
  const project = projectId.value, name = loadedBlueprintName.value, submitted = blueprintContent.value
  return act(async (isCurrent) => {
    const document = await api.putBlueprint(
      project,
      name,
      submitted
    )
    if (!isCurrent() || project !== projectId.value || name !== loadedBlueprintName.value) return
    savedBlueprintContent.value = document.content
    loadedBlueprintName.value = document.name
    if (blueprintContent.value === submitted) blueprintEditing.value = false
  }, blueprintActionError)
}
const archiveBlueprint = () => {
  if (blueprintContent.value !== savedBlueprintContent.value) {
    blueprintActionError.value = '蓝图有未保存的修改，请先保存后归档'
    return
  }
  act(async (isCurrent) => {
    const archived = await api.archiveBlueprint(projectId.value, blueprintName.value)
    if (!isCurrent()) return
    blueprintReadSeq += 1
    blueprintName.value = ''
    loadedBlueprintName.value = ''
    blueprintContent.value = ''
    savedBlueprintContent.value = ''
    await readArchive(archived.archive_name)
  }, blueprintActionError)
}
/** 将低频管理操作收纳在当前蓝图菜单。 */
function handleBlueprintMenu({ key }) {
  if (key === 'rename') {
    renameBlueprintDraft.value = displayBlueprintName(loadedBlueprintName.value)
    renameBlueprintError.value = ''
    renameBlueprintOpen.value = true
    nextTick(() => document.getElementById('blueprint-rename-input')?.focus())
  } else if (key === 'delete') {
    openBlueprintDelete(false)
  } else if (key === 'archive') {
    const project = projectId.value, owner = user.uid, name = loadedBlueprintName.value
    Modal.confirm({
      title: '归档蓝图',
      content: `「${displayBlueprintName(loadedBlueprintName.value)}」归档后将从当前列表移出，可在历史蓝图中翻阅。`,
      okText: '归档',
      cancelText: '取消',
      onOk: () => { if (project === projectId.value && owner === user.uid && name === loadedBlueprintName.value) return archiveBlueprint() }
    })
  }
}

/** 重命名文件，保留页面中的未保存正文。 */
async function renameBlueprint() {
  if (busy.value) return
  const name = normalizeBlueprintName(renameBlueprintDraft.value)
  if (!name) {
    renameBlueprintError.value =
      '名称需以中文、英文或数字开头，可含常用标点，不含空格且不超过 120 字；中文较多时请适当缩短'
    return
  }
  busy.value = true
  renameBlueprintError.value = ''
  const project = projectId.value
  const owner = user.uid
  try {
    const renamed = await api.renameBlueprint(project, loadedBlueprintName.value, name)
    if (projectId.value !== project || owner !== user.uid) return
    blueprintReadSeq += 1
    blueprints.value = blueprints.value
      .map((doc) => (doc.name === loadedBlueprintName.value ? { ...doc, ...renamed } : doc))
      .sort((a, b) => a.name.localeCompare(b.name))
    blueprintName.value = renamed.name
    loadedBlueprintName.value = renamed.name
    renameBlueprintOpen.value = false
    message.success('蓝图已重命名')
  } catch (error) {
    if (projectId.value === project && owner === user.uid) renameBlueprintError.value = describeBoardError(error)
    if (project === projectId.value && owner === user.uid && [401, 403, 404].includes(error?.status || error?.response?.status)) await visibilityLost(error)
  } finally {
    if (project === projectId.value && owner === user.uid) busy.value = false
  }
}

/** 固定待删除蓝图，确认框明确显示名称与所属位置。 */
function openBlueprintDelete(archived) {
  const archive = archivedBlueprints.value.find(
    (item) => item.archive_name === selectedArchive.value
  )
  if (archived && !archive) return
  deleteBlueprintTarget.value = archived
    ? { name: archive.name, key: archive.archive_name, archived: true }
    : { name: loadedBlueprintName.value, key: loadedBlueprintName.value, archived: false }
  deleteBlueprintError.value = ''
  deleteBlueprintOpen.value = true
}

/** 永久删除成功后清理选择并刷新真实列表。 */
async function deleteBlueprint() {
  if (busy.value || !deleteBlueprintTarget.value) return
  const target = deleteBlueprintTarget.value
  const project = projectId.value
  const owner = user.uid
  busy.value = true
  deleteBlueprintError.value = ''
  try {
    if (target.archived) {
      await api.deleteBlueprintArchive(project, target.key)
      if (projectId.value !== project || owner !== user.uid) return
      archiveReadSeq += 1
      selectedArchive.value = ''
      archiveContent.value = ''
      archiveError.value = ''
      archiveLoading.value = false
    } else {
      await api.deleteBlueprint(project, target.key)
      if (projectId.value !== project || owner !== user.uid) return
      blueprintReadSeq += 1
      blueprintName.value = ''
      loadedBlueprintName.value = ''
      blueprintContent.value = ''
      savedBlueprintContent.value = ''
    }
    deleteBlueprintOpen.value = false
    message.success('蓝图已永久删除')
    await load()
  } catch (error) {
    if (projectId.value !== project || owner !== user.uid) return
    if ([401, 403, 404].includes(error?.status || error?.response?.status)) await visibilityLost(error)
    if (deleteBlueprintOpen.value) deleteBlueprintError.value = describeBoardError(error)
    else blueprintActionError.value = describeBoardError(error)
  } finally {
    if (project === projectId.value && owner === user.uid) busy.value = false
  }
}

const submitTopic = () =>
  act(async (isCurrent) => {
    const created = await api.createTopic(projectId.value, {
      title: topicDraftTitle.value,
      summary: topicDraftSummary.value
    })
    if (!isCurrent()) return
    topicDraftTitle.value = ''
    topicDraftSummary.value = ''
    topicComposerVisible.value = false
    selectedTopicId.value = created.id
    setTopicRoute(created.id)
  })
const saveTopicEdit = () => {
  if (!editingTopic.value || editingTopicId.value !== selectedTopic.value?.id) return
  return act(async (isCurrent) => {
    await api.updateTopic(projectId.value, editingTopicId.value, {
      title: editingTopicTitle.value,
      summary: editingTopicSummary.value,
      expected_outcome: editingTopicExpected.value,
      verification_conditions: editingTopicConditions.value,
      expected_revision: editingTopicRevision.value,
      reason: editingTopicReason.value
    })
    if (!isCurrent()) return
    setGovernanceDraft(user.uid, projectId.value, `topic-edit:${editingTopicId.value}`, null)
    editingTopic.value = false
  }, topicEditError)
}
const reviewTopic = (topic, approve) =>
  act(() => api.reviewTopic(projectId.value, topic.id, approve))
const createDecision = () =>
  act(async (isCurrent) => {
    await api.createDecision(projectId.value, {
      title: decisionTitle.value,
      conclusion: decisionConclusion.value,
      rationale: decisionRationale.value,
      topic_id: decisionTopicId.value || null,
      relation_type: decisionRelationType.value,
      target_decision_id: decisionTargetId.value || null
    })
    if (!isCurrent()) return
    decisionTitle.value = ''
    decisionConclusion.value = ''
    decisionRationale.value = ''
    decisionTopicId.value = undefined
    decisionRelationType.value = 'ordinary'
    decisionTargetId.value = undefined
  })
const createTask = () =>
  act(async (isCurrent) => {
    await api.createTask(projectId.value, {
      title: taskTitle.value,
      description: taskDescription.value,
      topic_id: taskTopicId.value || null,
      decision_id: taskDecisionId.value || null,
      assignee_agent_slug: taskAgentSlug.value || null
    })
    if (!isCurrent()) return
    taskTitle.value = ''
    taskDescription.value = ''
    taskTopicId.value = undefined
  })
const reviewTask = (task, approve) => act(() => api.reviewTask(projectId.value, task.id, approve))

async function showSession(item) {
  try {
    const detail = await codingSessionApi.detail(item.session_id)
    sessionDetails.value = { ...sessionDetails.value, [item.session_id]: detail.session || detail }
  } catch (error) {
    actionError.value = describeBoardError(error)
  }
}
let delegationPoll = null
async function pollDelegations() {
  if (
    loading.value ||
    busy.value ||
    !delegations.value.some(
      (item) => item.dispatch_state !== 'reclaimed' && !terminalTurn(item.remote_status)
    )
  )
    return
  const project = projectId.value
  const owner = user.uid
  try {
    const rows = await api.listDelegations(project)
    if (project === projectId.value && owner === user.uid) delegations.value = rows
  } catch {
    // 手动刷新仍可重试；轮询不覆盖页面上的其他错误。
  }
}
const refreshDelegation = (item) =>
  act(async () => {
    await api.getDelegation(projectId.value, item.operation_id)
  })
const collectDelegation = (item) =>
  act(() => api.collectDelegation(projectId.value, item.operation_id))

watch([projectId, () => user.uid], () => {
  createBlueprintOpen.value = false
  createBlueprintError.value = ''
  newBlueprintName.value = ''
  newBlueprintContent.value = ''
  newBlueprintBaseline.value = ''
  newBlueprintInitialized = false
  blueprintProjectType.value = 'unspecified'
  sharedBlueprintDirectory.value = false
  renameBlueprintOpen.value = false
  deleteBlueprintOpen.value = false
  blueprintReadSeq += 1
  archiveReadSeq += 1
  blueprints.value = []
  archivedBlueprints.value = []
  selectedArchive.value = ''
  archiveContent.value = ''
  archiveError.value = ''
  archiveLoading.value = false
  agents.value = []
  delegations.value = []
  blueprintName.value = ''
  loadedBlueprintName.value = ''
  blueprintContent.value = ''
  savedBlueprintContent.value = ''
  blueprintActionError.value = ''
  selectedTopicId.value = ''
  topicRows.value = []
  formalWorks.value = []
  showArchivedTopics.value = false
  topicCommentError.value = ''
  topicComposerVisible.value = false
  topicDraftTitle.value = ''
  topicDraftSummary.value = ''
  editingTopic.value = false
  editingTopicTitle.value = ''
  editingTopicSummary.value = ''
  decisionTitle.value = ''
  decisionConclusion.value = ''
  decisionRationale.value = ''
  decisionTopicId.value = undefined
  taskTopicId.value = undefined
  draftScope = { user: user.uid, project: projectId.value }
  restoreForms()
  actionError.value = ''
  busy.value = false
  load()
})
watch(
  () => route.query.topic_id,
  (topicId) => {
    const requested = String(topicId || '')
    if (!requested || !allTopics.value.some((item) => item.id === requested)) return
    if (requested !== selectedTopicId.value && !canLeaveTopicEditor()) {
      setTopicRoute(selectedTopicId.value)
      return
    }
    selectedTopicId.value = requested
  }
)
watch(
  [loading, () => route.query.task_id, () => route.query.decision_id, () => route.query.topic_id],
  async ([isLoading, taskId, decisionId, topicId]) => {
    if (isLoading) return
    const recordId = taskId ? `task-${taskId}` : decisionId ? `decision-${decisionId}` : topicId ? 'topics' : ''
    if (!recordId) return
    await nextTick()
    jumpTo(recordId)
  },
  { immediate: true }
)
watch(
  [loading, () => route.hash],
  async ([isLoading, hash]) => {
    if (isLoading || !hash) return
    await nextTick()
    jumpTo(hash.slice(1))
  },
  { immediate: true }
)
onMounted(() => {
  restoreForms()
  load()
  delegationPoll = setInterval(pollDelegations, 10000)
})
onUnmounted(() => { active = false; clearInterval(delegationPoll) })
</script>

<style scoped lang="less">
.current-topic-context { display: flex; flex-direction: column; gap: 10px; }
.context-card { padding: 12px; border: 1px solid var(--gray-150); border-radius: 6px; overflow-wrap: anywhere; }
.context-link { padding: 0; background: none; border: none; color: var(--main-color); cursor: pointer; text-align: left; }
summary { min-height: 36px; cursor: pointer; color: var(--gray-700); }
.workbench-content { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
.blueprint-reader { min-width: 0; overflow-wrap: anywhere; }
.workbench-nav button[aria-pressed="true"] { background: var(--main-30); color: var(--main-color); border-color: var(--main-color); }
.workbench-nav button:focus-visible { outline: 2px solid var(--main-color); outline-offset: 2px; }
.workbench-nav button { min-height: 44px; }
.blueprint-history summary { cursor: pointer; color: var(--color-text-secondary); }
.blueprint-shared-hint { margin: 10px 0; }
.inspection-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.inspection-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: var(--page-padding);
  background: var(--gray-25);
}
.inspection-body :deep(a) {
  color: var(--main-color);
}
.workbench-intro {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 26px 28px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
}
.workbench-kicker {
  margin: 0 0 8px;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.workbench-intro h1 {
  margin: 0;
  color: var(--gray-1000);
  font-size: 25px;
}
.workbench-intro p:last-child {
  margin: 8px 0 0;
  color: var(--gray-600);
}
.workbench-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.workbench-nav button {
  padding: 7px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-700);
  cursor: pointer;
}
.workbench-nav button:hover {
  border-color: var(--main-color);
  color: var(--main-color);
}
.inspection-state {
  margin: 40px auto;
}
.workbench-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
  scroll-margin-top: 16px;
}
.section-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--gray-100);
}
.section-index {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 7px;
  background: var(--main-30);
  color: var(--main-color);
  font-size: 12px;
  font-weight: 700;
}
.section-heading h2 {
  margin: 0;
  font-size: 17px;
  color: var(--gray-1000);
}
.section-heading p {
  margin: 4px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}
.workbench-section h2 {
  color: var(--gray-1000);
}
.form-row,
.workbench-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.form-row > .ant-input {
  flex: 1;
  min-width: 180px;
}
.workbench-links {
  gap: 8px;
}
.workbench-links a {
  padding: 7px 10px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-0);
  font-size: 13px;
  color: var(--gray-700);
  text-decoration: none;
}
.workbench-links a:visited,
.workbench-links a:hover,
.workbench-links a:active {
  color: var(--gray-700);
  text-decoration: none;
}
.workbench-links a:hover {
  border-color: var(--main-color);
}
.workbench-list > li {
  align-items: flex-start;
}
.workbench-list > li > strong {
  min-width: 150px;
}
.workbench-list > li > span:not(.ant-tag) {
  color: var(--gray-600);
  overflow-wrap: anywhere;
}
@media (max-width: 680px) {
  .inspection-page :deep(.page-header) {
    height: auto;
    min-height: 48px;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding-block: 12px;
  }
  .inspection-page :deep(.page-header-title) {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .inspection-page :deep(.page-header-right) {
    flex-wrap: wrap;
  }
  .workbench-intro {
    align-items: flex-start;
    flex-direction: column;
    padding: 20px;
  }
  .workbench-section {
    padding: 18px;
  }
}
.workbench-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}
.workbench-list > li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--gray-100);
  border-radius: 8px;
}
.workbench-list strong {
  color: var(--gray-1000);
}
.topic-composer,
.decision-entry {
  display: grid;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-25);
}
.composer-heading,
.topic-sidebar-heading,
.discussion-heading,
.topic-review-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.composer-heading h3,
.discussion-heading h4 {
  margin: 0;
  color: var(--gray-1000);
  font-size: 16px;
}
.composer-heading p,
.discussion-heading p,
.topic-review-actions p {
  margin: 4px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}
.topic-layout {
  display: grid;
  grid-template-columns: minmax(230px, 290px) minmax(0, 1fr);
  align-items: start;
  gap: 16px;
}
.topic-sidebar {
  display: grid;
  gap: 8px;
  min-width: 0;
}
.topic-sidebar-heading {
  justify-content: space-between;
  padding: 4px 2px;
  color: var(--gray-800);
}
.topic-sidebar-heading span,
.discussion-heading > span {
  color: var(--gray-500);
  font-size: 12px;
}
.topic-list-empty {
  padding: 12px;
}
.topic-list-card {
  display: grid;
  gap: 8px;
  padding: 9px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
}
.topic-list-card.active {
  border-color: var(--main-color);
  box-shadow: 0 0 0 2px var(--main-30);
}
.topic-select {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 2px;
  border: 0;
  background: transparent;
  color: var(--gray-800);
  cursor: pointer;
  text-align: left;
}
.topic-select:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 2px;
}
.topic-list-title {
  min-width: 0;
  color: var(--gray-1000);
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.topic-select :deep(.ant-tag) {
  margin: 0;
}
.topic-list-summary {
  grid-column: 1 / -1;
  display: -webkit-box;
  overflow: hidden;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.topic-detail,
.topic-detail-empty {
  min-width: 0;
  padding: 20px;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-0);
}
.topic-detail {
  display: grid;
  gap: 18px;
}
.topic-detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--gray-100);
}
.topic-detail-heading h3 {
  margin: 0 0 8px;
  color: var(--gray-1000);
  font-size: 20px;
  overflow-wrap: anywhere;
}
.topic-detail-heading .eyebrow {
  margin: 0 0 6px;
  color: var(--main-color);
  font-size: 11px;
}
.topic-proposal-body,
.discussion-post {
  min-width: 0;
  color: var(--gray-800);
  overflow-wrap: anywhere;
}
.topic-proposal-body :deep(.yk-markdown-preview),
.discussion-post :deep(.yk-markdown-preview) {
  line-height: 1.75;
}
.topic-editor {
  display: grid;
  gap: 12px;
}
.discussion-thread {
  display: grid;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--gray-100);
}
.discussion-heading {
  align-items: flex-start;
}
.discussion-empty {
  margin: 0;
  padding: 18px;
  border-radius: 7px;
  background: var(--gray-25);
  color: var(--gray-500);
  text-align: center;
}
.discussion-post {
  padding: 14px 16px;
  border: 1px solid var(--gray-100);
  border-radius: 8px;
  background: var(--gray-25);
}
.discussion-post > header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.discussion-post > header strong {
  color: var(--gray-900);
}
.discussion-post time {
  color: var(--gray-500);
  font-size: 12px;
}
.discussion-reply {
  display: grid;
  gap: 9px;
  padding-top: 8px;
}
.topic-review-actions {
  align-items: center;
  padding-top: 14px;
  border-top: 1px solid var(--gray-100);
}
.topic-review-actions strong {
  color: var(--gray-800);
}
.topic-review-note {
  margin: 0;
}
.topic-detail-empty {
  display: grid;
  justify-items: start;
  gap: 9px;
  color: var(--gray-500);
}
.topic-detail-empty strong {
  color: var(--gray-800);
}
.topic-detail-empty p {
  margin: 0;
}
.decision-entry {
  scroll-margin-top: 16px;
}
.decision-records {
  display: grid;
  gap: 10px;
  scroll-margin-top: 16px;
}
.decision-card {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  scroll-margin-top: 16px;
}
.decision-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.decision-card > header strong {
  color: var(--gray-1000);
}
.decision-card > p {
  margin: 0;
}
.selected-governance-item {
  border-color: var(--main-color) !important;
  box-shadow: 0 0 0 2px var(--main-30);
}
.delegation-list {
  flex-basis: 100%;
  margin: 0;
  padding-left: 20px;
}
.delegation-list li {
  margin: 6px 0;
}
.delegation-list p {
  margin: 4px 0;
  overflow-wrap: anywhere;
}
.hint {
  color: var(--gray-500);
  font-size: 12px;
}
.blueprint-history {
  padding-top: 16px;
  border-top: 1px solid var(--gray-100);
}
.blueprint-history h3 {
  margin: 0 0 12px;
  color: var(--gray-900);
  font-size: 15px;
}
.blueprint-history h3 span {
  margin-left: 5px;
  color: var(--gray-500);
  font-size: 12px;
}
.archive-layout {
  display: grid;
  grid-template-columns: minmax(170px, 220px) minmax(0, 1fr);
  gap: 14px;
}
.archive-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow: auto;
}
.archive-list button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--gray-150);
  border-radius: 7px;
  background: var(--gray-0);
  color: var(--gray-800);
  cursor: pointer;
  text-align: left;
}
.archive-list button.active {
  border-color: var(--main-color);
  background: var(--main-30);
}
.archive-list small {
  color: var(--gray-500);
}
.archive-preview {
  min-width: 0;
  min-height: 180px;
  max-height: 360px;
  overflow: auto;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 7px;
  background: var(--gray-25);
}
@media (max-width: 680px) {
  .archive-layout {
    grid-template-columns: 1fr;
  }
  .topic-layout {
    grid-template-columns: 1fr;
  }
  .topic-sidebar {
    max-height: 360px;
    overflow-y: auto;
  }
  .topic-review-actions {
    align-items: flex-start;
    flex-direction: column;
  }
  .topic-detail,
  .topic-detail-empty {
    padding: 15px;
  }
}
.blueprint-more {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.blueprint-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px 0;
}
.blueprint-dialog label {
  color: var(--color-text);
  font-weight: 500;
}
.blueprint-dialog p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}
.blueprint-delete-target {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  background: var(--gray-25);
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  color: var(--color-text-secondary);
}
.blueprint-delete-target > svg {
  flex-shrink: 0;
}
.blueprint-delete-target div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.blueprint-delete-target strong {
  color: var(--color-text);
  overflow-wrap: anywhere;
}
.blueprint-delete-target span {
  font-size: 12px;
}
.archive-preview-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding-bottom: 10px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--gray-150);
  color: var(--color-text-secondary);
  font-size: 12px;
}
.archive-preview-heading :deep(button) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.archive-list strong {
  overflow-wrap: anywhere;
}
</style>
