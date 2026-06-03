"""LLM Prompt 模板，复用自图数据库 stage2_extract.py 和 stage2_decompose.py"""


JUDGMENT_PROMPT = """你是银行业合规专家，负责判断内规条款与外规条款的匹配关系。

## 背景
外规是监管部门发布的法规，内规是银行内部制定的制度。你需要判断内规条款是否正确落实了外规要求。

## 外规条款
文书：{outer_doc_title}
条号：{outer_article_no}
内容：{outer_content}
语义要素：
- 主体：{outer_subjects}
- 客体：{outer_objects}
- 业务维度：{outer_biz_dims}
- 行为模态：{outer_action}
- 阈值/条件：{outer_threshold}

## 内规条款
文书：{inner_doc_title}
条号：{inner_article_no}
内容：{inner_content}
语义要素：
- 主体：{inner_subjects}
- 客体：{inner_objects}
- 业务维度：{inner_biz_dims}
- 行为模态：{inner_action}

## 判断标准
请根据以下标准判断两者的关系：

1. **高度符合**：内规落实了外规的核心要求，主体/客体/行为模态基本对应。允许非实质差异（如机构名称不同但职能等价、措辞差异但语义不矛盾），但不允许范围缩小、主体遗漏、阈值放宽等削弱性差异。
2. **基本一致**：内规落实了外规的大部分核心要求，但存在轻微的范围收窄或覆盖不全（如未覆盖某一个次要主体、未明确某一个非核心时限），整体方向一致，属于可接受的合规落差。
3. **部分冲突**：内规存在以下任一实质性问题：(a) 主体覆盖不全（遗漏外规要求的关键主体）；(b) 客体范围缩小（未覆盖外规要求的核心业务/事项）；(c) 阈值/时限放宽；(d) 增加了外规没有的例外条款；(e) 将外规强制性要求降级。
4. **直接冲突**：内规与外规要求正面对立，行为模态相反（如外规规定"应当"、内规规定"不得"），或内规明确允许外规禁止的行为。
5. **无关**：内外规条款无业务对应关系，不属于同一领域或主题。

## 关键一致性规则
conflict_type 必须与 label 严格自洽：
- label 为"高度符合"或"基本一致" → conflict_type 必须是"无冲突"，description 填"无"
- label 为"部分冲突"或"直接冲突" → conflict_type 不能是"无冲突"，必须指出具体冲突类型
- 如果 reasoning 中描述了主体缺失、客体缩小、阈值放宽、行为矛盾等实质性差异，则 label 必须为"部分冲突"或"直接冲突"，不得判为"基本一致"或"高度符合"

## JSON 完整性硬约束（极其重要）
你必须输出完整、合法的 JSON。不允许输出不完整的 JSON、不允许截断、不允许省略任何字段。
如果条款内容过长无法完整分析，也必须在 JSON 内注明，但 JSON 结构本身必须完整闭合。
所有字符串值必须用双引号包裹，confidence 必须是数字，key_evidence 必须是数组。

## 输出格式
请严格按以下 JSON 格式输出，不要输出其他任何内容：
{{
  "label": "高度符合|基本一致|部分冲突|直接冲突|无关",
  "confidence": 0.0-1.0,
  "reasoning": "判断依据的简要说明（100字以内）",
  "key_evidence": ["关键证据1", "关键证据2"],
  "conflict_details": {{
    "conflict_type": "行为模态冲突|阈值突破|条件放宽|主体错位|客体不符|无冲突",
    "description": "具体冲突描述（如有），若无冲突则填'无'"
  }}
}}

注意：conflict_type 字段必须输出字符串值，不可为 null。当 label 为"无关"或"高度符合"时，conflict_type 输出"无冲突"。
"""


REVIEW_PROMPT = """你是银行业合规专家的质量评审员，负责审核条款匹配判定结果的质量。

## 待审核的判定结果
{judgment_result}

## 原始条款信息
外规条款：{outer_content}
内规条款：{inner_content}

## 审核要求

### 1. JSON 完整性校验（最高优先级）
- 判定结果必须是完整、合法、可解析的 JSON 对象
- 所有必填字段（label, confidence, reasoning, key_evidence, conflict_details）必须存在且非空
- label 必须是五个有效值之一：高度符合、基本一致、部分冲突、直接冲突、无关
- confidence 必须是 0.0-1.0 范围内的数字
- key_evidence 必须是非空数组（至少包含一条证据）
- conflict_details 必须是包含 conflict_type 和 description 的对象

### 2. 一致性校验
- label 与条款内容是否逻辑一致
- reasoning 是否能支撑 label 结论
- key_evidence 中的证据是否直接来源于条款内容（不得编造）
- conflict_type 与 label 是否自洽：
  * 高度符合/基本一致 → conflict_type 必须为"无冲突"
  * 部分冲突/直接冲突 → conflict_type 不能为"无冲突"

### 3. 评分标准
- 90-100分：完全正确，JSON 完整，无需修改
- 70-89分：基本正确，但有小瑕疵（如 reasoning 不够精准）
- 50-69分：存在逻辑问题或 JSON 字段不完整，需要修改
- 0-49分：JSON 不可解析、label 错误或格式严重不符

## 输出格式
请严格按以下 JSON 格式输出，不要输出其他任何内容：
{{
  "format_valid": true|false,
  "format_issues": ["问题描述1"],
  "consistency_valid": true|false,
  "consistency_issues": ["问题描述1"],
  "score": 0-100,
  "passed": true|false,
  "feedback": "修改建议（如未通过，请具体指出哪里需要改）",
  "corrected_result": {{...}}
}}

注意：corrected_result 仅在 score < 70 且你有把握给出正确结果时填写，否则填 null。
"""


RETRY_JUDGMENT_PROMPT = """{original_prompt}

## 上次判定结果（未通过评审）
{judgment_result}

## 评审反馈
评分：{score}
格式问题：{format_issues}
一致性问题：{issues}
修改建议：{feedback}

请根据以上反馈重新进行判定。特别注意：
1. 必须输出完整、合法的 JSON，所有字段不能为空
2. label 与 conflict_type 必须自洽
3. key_evidence 至少包含一条具体证据
"""


CONFLICT_GENERATION_PROMPT = """你是银行业合规专家，需要基于给定的匹配条款对，构造一个合规冲突场景。

## 外规条款
文书：{outer_doc_title}
条号：{outer_article_no}
内容：{outer_content}

## 内规条款
文书：{inner_doc_title}
条号：{inner_article_no}
内容：{inner_content}

## 原始判断结果
标签：{original_label}
理由：{reasoning}

## 任务
请构造一个**合规冲突场景**，要求：
1. 场景必须涉及内外规条款的交互
2. 场景应产生"部分冲突"或"直接冲突"的判断
3. 场景应具有现实合理性，符合银行业务场景
4. 冲突可以是：行为模态矛盾、阈值突破、条件放宽、适用范围冲突等

## JSON 完整性硬约束（极其重要）
你必须输出完整、合法的 JSON。不允许输出不完整的 JSON、不允许截断。
所有字符串值必须用双引号包裹，QA 答案要体现合规专业判断。

## 输出格式
请严格按以下 JSON 格式输出，不要输出其他任何内容：
{{
  "conflict_scenario": "冲突场景描述（150-250字，包含具体的业务情境）",
  "conflict_type": "部分冲突|直接冲突",
  "conflict_reason": "为什么这个场景会产生冲突（50字以内）",
  "qa_pair": {{
    "instruction": "基于以下场景，判断内规条款是否与外规条款存在冲突？",
    "input": "场景描述 + 条款信息",
    "output": "合规分析答案（包含冲突判断和理由，100-200字）"
  }}
}}

注意：
- conflict_type 必须是"部分冲突"或"��接��突"
- 场景描述要具体，避免泛泛而谈
- QA 答案要体现合规专业判断
"""


def build_judgment_prompt(
    outer_doc_title: str,
    outer_article_no: str,
    outer_content: str,
    outer_subjects: list,
    outer_objects: list,
    outer_biz_dims: list,
    outer_action: str,
    outer_threshold: str,
    inner_doc_title: str,
    inner_article_no: str,
    inner_content: str,
    inner_subjects: list,
    inner_objects: list,
    inner_biz_dims: list,
    inner_action: str,
) -> str:
    """构建判定 Prompt"""
    return JUDGMENT_PROMPT.format(
        outer_doc_title=outer_doc_title,
        outer_article_no=outer_article_no,
        outer_content=outer_content,
        outer_subjects=", ".join(outer_subjects) if outer_subjects else "无",
        outer_objects=", ".join(outer_objects) if outer_objects else "无",
        outer_biz_dims=", ".join(outer_biz_dims) if outer_biz_dims else "无",
        outer_action=outer_action or "无",
        outer_threshold=outer_threshold or "无",
        inner_doc_title=inner_doc_title,
        inner_article_no=inner_article_no,
        inner_content=inner_content,
        inner_subjects=", ".join(inner_subjects) if inner_subjects else "无",
        inner_objects=", ".join(inner_objects) if inner_objects else "无",
        inner_biz_dims=", ".join(inner_biz_dims) if inner_biz_dims else "无",
        inner_action=inner_action or "无",
    )


def build_review_prompt(
    judgment_result: str,
    outer_content: str,
    inner_content: str,
) -> str:
    """构建评审 Prompt"""
    return REVIEW_PROMPT.format(
        judgment_result=judgment_result,
        outer_content=outer_content,
        inner_content=inner_content,
    )


def build_retry_prompt(
    original_prompt: str,
    judgment_result: dict,
    review_result: dict,
) -> str:
    """构建带反馈信息的重试 Prompt"""
    return RETRY_JUDGMENT_PROMPT.format(
        original_prompt=original_prompt,
        judgment_result=str(judgment_result),
        score=review_result.get("score", 0),
        format_issues=", ".join(review_result.get("format_issues", [])),
        issues=", ".join(review_result.get("consistency_issues", [])),
        feedback=review_result.get("feedback", ""),
    )


def build_conflict_generation_prompt(
    outer_doc_title: str,
    outer_article_no: str,
    outer_content: str,
    inner_doc_title: str,
    inner_article_no: str,
    inner_content: str,
    original_label: str,
    reasoning: str,
) -> str:
    """构建冲突场景生成 Prompt"""
    return CONFLICT_GENERATION_PROMPT.format(
        outer_doc_title=outer_doc_title,
        outer_article_no=outer_article_no,
        outer_content=outer_content,
        inner_doc_title=inner_doc_title,
        inner_article_no=inner_article_no,
        inner_content=inner_content,
        original_label=original_label,
        reasoning=reasoning,
    )
