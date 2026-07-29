# bid-tech-fact-curator 细则

本文件是 SKILL.md 的配套细则：三类任务的判据、校验表、置信度指引与示例。修改判断行为前必读。

## 一、证据简报（brief）怎么用

`factcurate <manifest>` 脚本只做机械工作，产出 `briefFile`：

- `fields[].snippets`：按 label / reviewLabel 在招标文件与素材全文中检索到的原文片段（含来源名）。
- `fields[].flags`：对 extracted 字段的机械脏数据标记：
  - `serial-text`：值疑似表格跨列串行（多个数值用 `/` 连接、或数值后拖了另一个字段的中文名）；
  - `range`：数值超出常见合理区间（校验表见下）；
  - `unit-missing`：label 含单位标注（如 `（m/s）`）但字段 unit 为空。

brief 只是线索：**取值结论必须回到原文确认上下文**（该数值修饰的是不是这个字段、是要求值还是保证值、是哪个机型/机位的）。

## 二、长尾补抽（fill）判据

1. 先在 snippets 里找候选；不够时按字段 `materialClass` 定向用 Bash（grep -n 定位 + sed -n 取段）读同类素材，或检索 tenderSources 的 combined 全文字段同义词（招标类字段只查 tenderSources）。
2. 区分「招标要求值」与「投标人保证值」：字段 label 写明"招标"（如招标单机容量）取招标文件的要求值；写明"保证/承诺"的取承诺函或保证条款中的值。
3. 文本型字段（塔筒型式、箱变配置等）摘录原文短句即可，不要自行概括发挥。
4. 一个字段在多处出现不同值时，取招标文件正文中对本项目生效的那一处，并在 evidence 说明；无法裁决就给空值 + 说明，不硬填。

## 三、脏数据清洗（fix）判据

| 问题类型 | 判据 | 修正建议 |
|---|---|---|
| 跨列串行 | 值形如 `7.36/6.86/7.20 风电场保证年上网电量(MWh)`：多个数值 + 另一字段名 | 回原文表格确认本字段列，取本列的值（通常是第一列或按行对齐的列） |
| 数值区间 | 超出下表合理区间 | 回原文核对是否抄错行/抄错单位 |
| 单位错配 | label 单位与值数量级明显不符（如 m/s 的风速写成 km/h 量级） | 按原文单位换算或改写 unit |

常见合理区间（与后端抽取校验同源）：

- 年平均风速 2~15 m/s；极端风速 20~100 m/s
- 轮毂高度 40~250 m；叶轮直径 50~350 m
- 空气密度 0.7~1.5 kg/m3；湍流强度 0~1；风剪切 0~1
- 机组台数 1~1000 台；单机容量 0.5~20 MW
- 可利用率 80~100 %；保证有效小时数 1~8760 h

校验无问题的字段不要出现在 suggestions 里。

## 四、素材类别对照（materialClass 定向）

字段的 `materialClass` 由清单 `referenceFile` 归一而来，是定向找素材的指路牌：

| materialClass | referenceFile 特征 | 素材文件名/路径特征 |
|---|---|---|
| wind_resource | 项目定制-风资源报告 | 风资源、测风 |
| tower_quantity | 项目定制-塔架与基础工程量 | 塔架、工程量 |
| bending_moment | 项目定制-基础弯矩表（清单原文 typo「基础弯矩表表」） | 弯矩 |
| hours_commitment | 项目定制-发电小时数承诺函 | 承诺函、小时数承诺 |
| production_base | 项目定制-项目生产制造基地专题 | 生产基地、基地专题、供货制造基地 |
| cert | 认证证书（优先型式认证，其次设计认证） | 认证、证书、型式 |
| tender | 招标文件 | 无素材，只从 tenderSources 取数 |
| platform / derived / none | 平台输入 / 自动生成 / "/" | 无需素材 |

用法：处理某字段时先看它的 `materialClass`，在 materials 里挑同类素材（`materialClass` 相同）优先读；
`tender` 类字段只查 tenderSources。素材的 `crossProject: true` 表示来自其他项目（`homeProject` 为来源项目名），
引用前必须核对正文中项目名/场址/机型与本项目一致，evidence 保留素材 id；拿不准就 `action: "confirm"` 写清疑点。

## 五、口径建议（confirm-advice）判据

1. 字段已有值：判断现有值与原文口径是否一致（版本、保证值 vs 考核值、含税与否等），`suggestedValue` 留空，`evidence` 写口径判断 + 引用。
2. 字段无值但原文有口径：`suggestedValue` 给建议答案，`action` 仍为 `confirm-advice`。
3. 原文也说不清口径：留空 + evidence 写明歧义点，交人工裁决。

## 六、置信度指引

- 0.9~1.0：原文直接写明该字段的值，上下文无歧义
- 0.7~0.9：原文有值但需简单判断（单位换算、表格定位）
- 0.4~0.7：多处出现或口径不完全确定
- < 0.4：只找到间接线索，强烈建议人工复核

## 七、完整输出示例

```json
{
  "schema": "bid-tech-fact-curate-v1",
  "suggestions": [
    {
      "fieldKey": "招标单机容量出口端mw",
      "suggestedValue": "10",
      "unit": "MW",
      "evidence": "招标文件《第一章 招标公告》：单机容量不小于10MW（combined.txt 第 3 段）",
      "confidence": 0.92,
      "action": "fill"
    },
    {
      "fieldKey": "年平均风速",
      "suggestedValue": "7.36",
      "unit": "m/s",
      "evidence": "原值「7.36/6.86/7.20 风电场保证年上网电量(MWh)」为发电量保证表跨列串行；风资源报告表2首行 7.36 m/s 为本字段值",
      "confidence": 0.78,
      "action": "fix"
    },
    {
      "fieldKey": "塔筒型式",
      "suggestedValue": "",
      "unit": "",
      "evidence": "检索招标文件 combined 全文与 3 份项目素材，未出现塔筒型式/塔架型式相关要求",
      "confidence": 0.0,
      "action": "fill"
    }
  ]
}
```
