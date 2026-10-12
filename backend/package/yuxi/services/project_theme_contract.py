"""项目主题的纯定义、组件输入与导航契约。"""

from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

Name = Annotated[str, Field(min_length=1)]
Version = Annotated[int, Field(strict=True, ge=1, le=1)]


class ClosedModel(BaseModel):
    """拒绝包和事件中的扩展执行字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class Asset(ClosedModel):
    """包内资源声明，不携项目文件路径。"""

    path: Name
    mediaType: Literal["application/json", "image/png"]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def check_path(self):
        """资源成员仅位于assets相对目录。"""
        parts = self.path.split("/")
        if (
            not self.path.startswith("assets/")
            or any(p in ("", ".", "..") for p in parts)
            or "\\" in self.path
            or ":" in self.path
            or PurePosixPath(self.path).is_absolute()
        ):
            raise ValueError("asset_path: 资源必须是assets下的普通相对成员")
        return self


class Manifest(ClosedModel):
    """可携主题包清单，身份和绑定由宿主另行提供。"""

    formatVersion: Version
    componentAbi: Version
    theme: Literal["theme.json"]
    source: Name
    files: dict[Name, Literal["application/json", "image/png"]]
    assets: dict[Name, Asset]


class ProjectBinding(ClosedModel):
    """当前项目摘要。"""

    kind: Literal["business"]
    resource: Literal["project"]


class RecordsBinding(ClosedModel):
    """固定业务集合及可读选择范围。"""

    kind: Literal["business"]
    resource: Literal["topics", "decisions", "workTasks"]
    scope: Literal["project", "selectedTopic"]


class TopicBinding(ClosedModel):
    """当前选定议题。"""

    kind: Literal["business"]
    resource: Literal["selectedTopic"]


class DiscussionBinding(ClosedModel):
    """选定议题的讨论，不定义全局讨论集合。"""

    kind: Literal["business"]
    resource: Literal["discussions"]


class ResourceBinding(ClosedModel):
    """声明的文件或包内资源alias。"""

    kind: Literal["file", "asset"]
    alias: Name


class PageEvent(ClosedModel):
    """选择当前包内页面。"""

    kind: Literal["page"]
    pageId: Name


class ObjectEvent(ClosedModel):
    """打开宿主确认归属的准确业务对象。"""

    kind: Literal["object"]
    objectType: Literal["topic", "decision", "workTask"]
    id: Name


class SelectTopicEvent(ClosedModel):
    """改变当前议题选择。"""

    kind: Literal["selectTopic"]
    id: Name


NavigationEvent = Annotated[PageEvent | ObjectEvent | SelectTopicEvent, Field(discriminator="kind")]


class BlockBase(ClosedModel):
    """可信组件的有限编排属性。"""

    id: Name
    title: Name
    region: Literal["summary", "main", "aside"]
    action: PageEvent | None = None


class SummaryBlock(BlockBase):
    """项目摘要或目标说明。"""

    type: Literal["summary"]
    binding: ProjectBinding
    variant: Literal["counts", "description"]


class RecordsBlock(BlockBase):
    """同类型业务对象集合的受控表现。"""

    type: Literal["records"]
    binding: RecordsBinding
    variant: Literal["list", "table", "selector", "compactSelector", "conclusions", "attention", "history"]
    statuses: list[Name] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_variant(self):
        """表现模式不改变业务类型或选择语义。"""
        required = {
            "table": "topics",
            "selector": "topics",
            "compactSelector": "topics",
            "conclusions": "decisions",
            "history": "decisions",
            "attention": "workTasks",
        }.get(self.variant)
        if required and self.binding.resource != required:
            raise ValueError("record_variant: 表现模式与业务对象类型不匹配")
        if self.binding.resource == "topics" and self.binding.scope != "project":
            raise ValueError("record_scope: 议题目录使用项目范围")
        return self


class TopicBlock(BlockBase):
    """选定议题的问题和预期产出。"""

    type: Literal["topic"]
    binding: TopicBinding


class DiscussionBlock(BlockBase):
    """选定议题的只读讨论。"""

    type: Literal["discussion"]
    binding: DiscussionBinding


class JsonBlock(BlockBase):
    """资料JSON，与主题定义分开消费。"""

    type: Literal["json"]
    binding: ResourceBinding


class ImageBlock(BlockBase):
    """PNG资料和必要的等价描述。"""

    type: Literal["image"]
    binding: ResourceBinding
    alt: Name


Block = Annotated[
    SummaryBlock | RecordsBlock | TopicBlock | DiscussionBlock | JsonBlock | ImageBlock,
    Field(discriminator="type"),
]


class Page(ClosedModel):
    """有限页面布局，不携CSS或组件代码。"""

    id: Name
    title: Name
    description: Name
    layout: Literal["overview", "reading", "full"]
    blocks: Annotated[list[Block], Field(min_length=1)]


class Theme(ClosedModel):
    """独立主题定义，显示名不改议题类型。"""

    id: Name
    version: Name
    name: Name
    topicLabel: Name
    pages: Annotated[list[Page], Field(min_length=1)]


class ThemePackage(ClosedModel):
    """已解析包的定义契约，ZIP边界由后继parser拥有。"""

    manifest: Manifest
    theme: Theme

    @model_validator(mode="after")
    def check_references(self):
        """闭合页、组件绑定与文件引用。"""
        page_ids = [p.id for p in self.theme.pages]
        if len(set(page_ids)) != len(page_ids):
            raise ValueError("duplicate_page: 页面ID重复")
        paths = [a.path for a in self.manifest.assets.values()]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate_asset: 资源成员重复")
        for page in self.theme.pages:
            ids = [b.id for b in page.blocks]
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate_block: 页面内组件ID重复")
            for block in page.blocks:
                if block.action and block.action.pageId not in page_ids:
                    raise ValueError("page_reference: 导航指向未定义页面")
                if isinstance(block, JsonBlock | ImageBlock):
                    binding = block.binding
                    media = (
                        self.manifest.files.get(binding.alias)
                        if binding.kind == "file"
                        else getattr(self.manifest.assets.get(binding.alias), "mediaType", None)
                    )
                    expected = "application/json" if isinstance(block, JsonBlock) else "image/png"
                    if media != expected:
                        raise ValueError("resource_reference: alias未声明或MIME与组件不匹配")
        return self


class LoadedThemePackage(BaseModel):
    """宿主加载DTO，来源引用独立于作者主题ID及可携ZIP。"""

    model_config = ConfigDict(extra="allow", strict=True)
    manifest: Manifest
    theme: Theme
    reference: Name
    digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def check_package(self):
        """加载DTO也必须闭合包内跨引用。"""
        ThemePackage(manifest=self.manifest, theme=self.theme)
        return self


class SourceDto(BaseModel):
    """保留原Owner的扩展字段，仅校验当前组件消费的投影。"""

    model_config = ConfigDict(extra="allow", strict=True)
    id: Name
    project_id: Name
    title: Name


class TopicDto(SourceDto):
    """议题投影，纳入与研讨进展分别保留。"""

    summary: str | None
    expected_outcome: str | None
    admission_status: str
    progress: str


class DecisionDto(SourceDto):
    """决定投影，可没有来源议题。"""

    topic_id: str | None
    conclusion: str | None
    rationale: str | None
    status: str
    revision_number: int


class WorkTaskDto(SourceDto):
    """正式任务投影，保留冻结来源版本。"""

    topic_id: str | None
    source_decision_id: str | None
    source_decision_revision: int | None
    number: Name
    description: str | None
    status: str

    @model_validator(mode="after")
    def check_source(self):
        """来源决定与版本保持成对。"""
        if (self.source_decision_id is None) != (self.source_decision_revision is None):
            raise ValueError("task_source: 来源决定和版本必须成对")
        return self


class ProjectDto(BaseModel):
    """项目摘要保留原项目身份。"""

    model_config = ConfigDict(extra="allow", strict=True)
    id: Name
    name: Name
    description: str | None


class ProjectCounts(ClosedModel):
    """组件实际消费的完整聚合计数。"""

    topics: Annotated[int, Field(ge=0)]
    workTasks: Annotated[int, Field(ge=0)]
    approvedDecisions: Annotated[int, Field(ge=0)]
    blockedTasks: Annotated[int, Field(ge=0)]


class ProjectInput(ClosedModel):
    """项目摘要与Owner聚合的明确计数。"""

    project: ProjectDto
    counts: ProjectCounts


class DiscussionDto(BaseModel):
    """只读讨论投影，内容固定属于topic_id。"""

    model_config = ConfigDict(extra="allow", strict=True)
    id: Name
    topic_id: Name
    content: str
    author_name: str
    created_at: str


class ResourceMetadata(ClosedModel):
    """资源字节的类型、大小与指纹。"""

    mediaType: Literal["application/json", "image/png"]
    size: Annotated[int, Field(ge=0)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class DecisionSourceRevision(BaseModel):
    """正式任务当次依据的只读投影，原snapshot字段可保留。"""

    model_config = ConfigDict(extra="allow", strict=True)
    decision_id: Name
    revision_number: Annotated[int, Field(ge=1)]
    conclusion: str | None


def contract_schemas() -> dict[str, Any]:
    """为前端与后续维护工具生成同源Schema。"""
    models = {
        "package": ThemePackage,
        "loadedPackage": LoadedThemePackage,
        "navigation": TypeAdapter(NavigationEvent),
        "project": ProjectInput,
        "topics": TypeAdapter(list[TopicDto]),
        "decisions": TypeAdapter(list[DecisionDto]),
        "workTasks": TypeAdapter(list[WorkTaskDto]),
        "selectedTopic": TopicDto,
        "discussions": TypeAdapter(list[DiscussionDto]),
        "resource": ResourceMetadata,
        "sourceRevision": DecisionSourceRevision,
    }
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **(model.json_schema() if isinstance(model, TypeAdapter) else model.model_json_schema()),
        }
        for name, model in models.items()
    }
