# 书籍分块采用无放回抽样

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/knowledge/chunking/ragflow_like/nlp.py

## 问题

书籍解析器抽样判断语言和标题类型。有放回抽样即使在文档短于样本上限时也会重复抽中正文并漏掉全部标题，同一份短文档可能随机从按节分块退化为整块合并。发布检查的全量 unit 暴露此问题。

## 决策

抽样使用 `random.sample`，样本数量仍取文档段落数与原有上限的较小值。短文档的全部段落均参与语言与标题识别，长文档继续采用有界随机样本。两个现有调用者均只统计语言或标题类别，不依赖样本顺序。

## 替代方案

- 只在测试中固定幸运随机种子：保留用户文档偶发错误。
- 全文扫描：改变长文档的采样成本与现有启发式范围。

## 后果

短文档的标题不会因重复抽样丢失；长文档仍可能因采样未覆盖稀疏标题而选择普通分块，此修复不承诺长文档分块完全确定。

## 验证

`test_book_chunking_hierarchical_merge` 使用独立 `random.Random` 实例，保留两节精确内容 oracle。种子 94 在原实现稳定得到一个错误合并块，修复后与种子 0 均返回两个带章标题的节。运行 `docker compose exec -T api uv run --no-sync pytest test/unit/plugins/test_ragflow_like_chunking.py -q`，由后端 unit workflow 阻断回归。此修复沿用抽样接口、上限与分块返回契约，可直接记录为完整局部 bug-fix。
