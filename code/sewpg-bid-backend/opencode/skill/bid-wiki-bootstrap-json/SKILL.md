---
name: bid-wiki-bootstrap-json
description: 根据参考 wiki 的目录、规则、同义词和骨架说明，输出“平台级 Wiki 装配规则库”的 starter JSON 蓝图。只输出 JSON，不写文件。
---

# 平台级 Wiki 初始化蓝图

你负责把参考 wiki 抽象成可导入系统的 starter wiki。

## 目标

- 输出“平台级 Wiki = 标书装配规则库”的初始化结构
- 强调：
  - index 是卡片目录
  - rules 是装配规则
  - synonyms 是检索映射
  - skeleton_section 是章节归属
- 平台级 Wiki 提供：
  - 通用专题卡
  - 技术标/商务标骨架映射
  - 同义词
  - 章节挂载规则
  - 条件规则
  - 项目级 Wiki 的覆盖模板说明

## 输出要求

1. 只输出 JSON，不要解释，不要 Markdown 代码块。
2. 结构固定为：

```json
{
  "summary": "一句简短总结",
  "rootTitle": "平台级Wiki（自动生成）",
  "nodes": [
    {
      "title": "节点标题",
      "markdownContent": "# 标题\n\n正文",
      "tags": ["通用材料"],
      "applicableTypes": ["通用"],
      "children": []
    }
  ]
}
```

3. 顶层至少包含：
   - 平台级Wiki说明
   - 章节骨架
   - 装配规则
   - 同义词映射
   - 通用卡片
   - 项目级Wiki模板

4. 通用卡片需要按参考 wiki 的主要专题目录分组。
5. 项目级Wiki模板中要明确：
   - `override`
   - `append`
   - `reference`

## 内容风格

- 用于系统初始化，不要生成太多细枝末节
- 节点内容要简洁、可读、可继续人工补充
- 不要发明具体项目数据
