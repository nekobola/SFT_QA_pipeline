# SFT 数据生成工作流

用于批量生成内外规条款匹配 QA 对，训练冲突判别大模型。

## 最新生成结果

| 数据集 | 数量 | 来源 |
|--------|------|------|
| 训练集 | **16,706** | 13,731 原始QA + 2,975 冲突QA |
| 验证集 | 392 | 条款级非重叠划分 |
| 失败率 | 0% | - |

### 标签分布（训练集）

| 标签 | 数量 | 占比 |
|------|------|------|
| 部分冲突 | 11,753 | 70.4% |
| 基本一致 | 3,213 | 19.2% |
| 高度符合 | 993 | 5.9% |
| 直接冲突 | 747 | 4.5% |

数据来源：11,757 部外规（JSON，486MB）× 约 7,000 条内规（DOCX）→ 约 9.6 亿理论组合 → 倒排索引筛选至约 37,000 候选对 → 并发 LLM 处理生成 QA。

---

## 架构设计

### 工作流总览

```
parse ──► filter ──► batch_process ──► split ──► persist
(解析条款)  (筛选候选对)  (并发LLM处理)  (划分数据集)  (持久化存储)
```

### 处理流程

1. **解析条款** — 外规从 JSON (`full_outer_data.json`) 直接解析结构；内规从 DOCX 解析。内规用 LLM 提取语义要素（subjects/objects/biz_dims/action），外规用内规语义要素做关键词匹配（避免逐条调用 LLM）。
2. **分层筛选** — 构建倒排索引，按匹配特征将候选对分层（L1/L2/L4），按比例采样后输出给 LLM 判定。
3. **批量并发处理** — ThreadPoolExecutor 20 并发调用 LLM：判断 → 评审 → 通过/重试/失败。对"高度符合"/"基本一致"的 pair 额外生成冲突场景 QA。处理过程中直接丢弃"无关"标签。
4. **划分数据集** — 条款级非重叠划分（val_clause_ratio=0.1），冲突 QA 跟随原始 QA 的划分。
5. **持久化存储** — 输出完整 JSONL + LLaMA Factory Alpaca 格式 SFT 文件 + 统计报告。

---

## 文件结构

```
.
├── config.yaml                    # 主配置文件
├── requirements.txt               # Python 依赖
├── run_concurrent.py              # 并发版主入口（推荐）
├── run_sft_pipeline.py            # LangGraph 串行版主入口
├── test_small_batch.py            # 小批量测试脚本
│
├── config/                        # 配置加载
│   ├── __init__.py
│   └── settings.py
│
├── parser/                        # 条款解析
│   ├── __init__.py
│   ├── outer_parser.py            # 外规 DOCX 解析（回退用）
│   ├── outer_json_parser.py       # 外规 JSON 解析（主路径）
│   ├── inner_parser.py            # 内规 DOCX 解析
│   ├── semantics_extractor.py     # 语义要素提取（LLM + 关键词匹配）
│   ├── synonym_normalizer.py      # 同义词归一化
│   ├── text_cleaner.py            # 文本清洗
│   └── base.py
│
├── filter/                        # 候选对预筛选
│   ├── __init__.py
│   ├── similarity.py              # 语义要素相似度计算
│   ├── hard_filter.py             # 硬筛选（OR 逻辑）
│   ├── soft_filter.py             # 分层筛选（L1-L4）
│   └── conflict_filter.py         # 冲突候选对专项筛选
│
├── llm/                           # LLM 调用
│   ├── __init__.py
│   ├── client.py                  # OpenAI 兼容客户端
│   ├── prompts.py                 # Prompt 模板（判断/评审/重试/冲突生成）
│   ├── parser.py                  # LLM 响应解析
│   ├── rate_limiter.py            # 令牌桶限流器
│   └── conflict_generator.py      # 冲突场景生成
│
├── workflow/                      # 工作流编排
│   ├── __init__.py
│   ├── nodes.py                   # LangGraph 串行节点（逐条判断→评审→重试）
│   ├── nodes_concurrent.py        # 并发节点（ThreadPool 批量处理 + 断点续传）
│   ├── graph.py                   # LangGraph 图定义
│   ├── state.py                   # 工作流状态 TypedDict
│   └── conditions.py              # 条件边逻辑
│
├── utils/                         # 工具
│   ├── __init__.py
│   ├── sft_converter.py           # SFT 格式转换
│   └── data_balance.py            # 数据平衡工具
│
├── tests/                         # 单元测试
│   ├── test_config.py
│   ├── test_filter.py
│   ├── test_llm_client.py
│   ├── test_llm_prompts.py
│   ├── test_parser.py
│   └── ...
│
├── data/                          # 数据目录
│   ├── outer/
│   │   └── full_outer_data.json   # 外规 JSON（11,757部法规）
│   └── inner/                     # 内规 DOCX 文件
│
└── output/                        # 输出目录
    ├── inner_clauses_with_semantics.json  # 内规语义缓存
    ├── outer_clauses_with_semantics.json  # 外规语义缓存
    ├── synonym_dictionary.json            # 同义词词典
    ├── candidate_pairs_index.json         # 候选对索引（轻量级）
    ├── train.jsonl                        # 完整训练数据
    ├── val.jsonl                          # 完整验证数据
    ├── train_original.jsonl               # 原始匹配 QA
    ├── train_conflict.jsonl               # 冲突场景 QA
    ├── train_sft.jsonl                    # SFT 训练集（Alpaca 格式）
    ├── val_sft.jsonl                      # SFT 验证集
    ├── failed_pairs.jsonl                 # 失败记录
    ├── stats.json                         # 统计报告
    └── .checkpoints/                      # 断点保存目录
```

---

## 配置说明

### config.yaml 关键配置

```yaml
# 数据路径
data:
  outer_dir: "data/outer"
  inner_dir: "data/inner"
  output_dir: "output"

# 解析器
parser:
  extract_semantics: true
  use_synonym_dict: true
  use_semantics_cache: true      # 内规语义缓存，外规每次从 JSON 重新解析
  llm_concurrency: 10            # 内规语义提取并发数

# 预筛选
filter:
  use_stratified: true
  layer_ratios:
    L1_strong: 0.45              # 强匹配 → 高度符合/基本一致
    L2_moderate: 0.40            # 中等匹配 → 部分冲突
    L3_weak: 0.0                 # 弱匹配 → 剔除
    L4_opposite: 0.15            # 反向匹配 → 直接冲突
  hard_filter:
    biz_dim_match: ">= 1"        # OR 逻辑：biz>=1 OR subj>=1 即可

# LLM
llm:
  max_concurrent_calls: 20
  rate_limit_per_second: 10.0
  judgment_model: "Qwen/Qwen3-Next-80B-A3B-Instruct"

# 评审
review:
  pass_threshold: 70
  max_retries: 2

# 目标规模
target:
  min_train_pairs: 10000
  max_train_pairs: 20000
  max_candidates_to_process: 50000
```

---

## 使用方法

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备数据

- 外规 JSON：`data/outer/full_outer_data.json`
- 内规 DOCX：`data/inner/*.docx`

### 3. 配置 LLM

编辑 `config.yaml`：

```yaml
llm:
  api_key: "your-api-key"
  base_url: "http://your-llm-server/v1"
  judgment_model: "your-model-name"
```

### 4. 运行

```bash
# 并发版（推荐，19k 候选对约 30 分钟）
python run_concurrent.py --candidates 50000

# 小规模测试（200 候选对）
python run_concurrent.py --candidates 200

# 小批量验证测试
python test_small_batch.py

# LangGraph 串行版（支持检查点恢复）
python run_sft_pipeline.py --mode run
```

---

## 核心机制

### 两种实现

项目提供两套独立的编排实现，推荐使用并发版：

| | `run_concurrent.py` | `run_sft_pipeline.py` |
|---|---|---|
| 编排方式 | 过程式 + `ThreadPoolExecutor` | `LangGraph` `StateGraph` |
| 处理策略 | 批量并发（20 线程） | 逐条串行（图循环） |
| 断点续传 | 每 5000 条保存 JSON 断点 | LangGraph `checkpoint` |
| 无关标签 | 直接丢弃 | 保留在数据集中 |
| 冲突生成 | 内嵌 | 未集成 |

两者共享 parser/filter/llm 模块，编排层互不依赖。

### 关键词过滤黑名单

外规语义提取时，从内规语义构建关键词表后，会过滤掉短词（<3 字符）和泛化黑名单词（如"银行""业务""人员""管理"等 30+ 个高频泛化词），避免关键词命中率过高导致候选对质量下降。

### 外规语义提取策略

- **内规**（~7,000 条）：用 LLM 逐条提取语义要素（subjects, objects, biz_dims, action），结果精确
- **外规**（~134,000 条）：基于内规已提取的实体关键词做文本匹配（关键词 in 条款文本），避免逐条调用 LLM

### 五级分类标签

| 标签 | 定义 |
|------|------|
| 高度符合 | 内规完全落实外规要求，语义要素完全对应 |
| 基本一致 | 内规落实外规要求，但表述或范围有细微差异 |
| 部分冲突 | 存在部分不一致，但核心要求仍有落实 |
| 直接冲突 | 与外规要求直接矛盾 |
| 无关 | 无对应关系（处理时直接丢弃） |

### 冲突场景生成

对判定为"高度符合"或"基本一致"的 pair，额外调用 LLM 构造一个合规冲突场景，生成对应的 QA 对，增加冲突样本的多样性。

### 断点续传

`node_batch_process` 每处理 5,000 条候选对保存一次断点到 `output/.checkpoints/`，中断后可从断点继续，完成后自动删除断点文件。

---

## 输出格式

### train_sft.jsonl / val_sft.jsonl（LLaMA Factory Alpaca 格式）

```json
{
  "instruction": "请判断以下内规条款是否与外规条款存在冲突？",
  "input": "外规条款：\n文书：商业银行法\n条号：第四十条\n内容：商业银行不得向关系人发放信用贷款\n\n内规条款：\n文书：信贷管理制度\n条号：第十五条\n内容：本行禁止向关系人发放信用贷款",
  "output": "判断结果：高度符合\n置信度：0.95\n理由：内规完全落实外规要求..."
}
```

---

## 参考文档

- 技术方案：`SFT-QA生成技术方案.md`
- LLaMA Factory：https://github.com/hiyouga/LLaMA-Factory
