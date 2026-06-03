#!/usr/bin/env python
"""SFT 数据生成工作流主入口"""
import argparse
from pathlib import Path
import json
import sys

from config import load_config
from utils.sft_converter import convert_dataset_to_sft


def main():
    parser = argparse.ArgumentParser(description="SFT 数据生成工作流")
    parser.add_argument(
        "--mode",
        choices=["run", "rework", "resume"],
        default="run",
        help="运行模式",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="配置文件路径",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="检查点 ID（resume 模式）",
    )
    args = parser.parse_args()

    # 加载配置
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)

    if args.mode == "run":
        # 正常运行
        run_workflow(config)
    elif args.mode == "rework":
        # 返工模式
        run_rework_mode(config)
    elif args.mode == "resume":
        # 从检查点恢复
        if not args.checkpoint:
            print("错误: resume 模式需要指定 --checkpoint")
            sys.exit(1)
        resume_from_checkpoint(args.checkpoint, config)


def run_workflow(config):
    """运行工作流"""
    import sys
    print("[SFT Pipeline] 开始运行...", flush=True)

    # 尝试导入工作流模块
    try:
        from workflow import build_workflow
        workflow_available = True
    except ImportError:
        print("[警告] workflow 模块未完全实现，使用模拟数据演示", flush=True)
        workflow_available = False

    if workflow_available:
        # 构建工作流
        workflow = build_workflow()
        app = workflow.compile()

        # 初始化状态
        initial_state = init_state(config.to_dict())
        print(f"[SFT Pipeline] 状态初始化完成", flush=True)

        # 执行（增加递归限制以处理大量候选对）
        # 每个候选对需要 3 步（judge → review → process_result）
        # 加上重试可能需要更多，设置足够高的限制
        print(f"[SFT Pipeline] 开始执行工作流...", flush=True)
        sys.stdout.flush()
        result = app.invoke(initial_state, {"recursion_limit": 1000000})
        print(f"[SFT Pipeline] 工作流执行完成", flush=True)

        # 转换为 SFT 格式
        convert_and_save_sft(result, config)

        # 打印统计
        print_stats(result)
    else:
        # 使用模拟数据演示
        run_demo_mode(config)


def run_demo_mode(config):
    """演示模式：使用模拟数据"""
    print("[SFT Pipeline] 演示模式...")

    # 创建模拟数据
    demo_train_set = [
        {
            "outer_clause": {
                "doc_title": "商业银行法",
                "article_no": "第四十条",
                "clause_text": "商业银行不得向关系人发放信用贷款",
                "subjects": ["商业银行"],
                "objects": ["信用贷款"],
                "biz_dims": ["信贷管理"],
                "action": "不得",
            },
            "inner_clause": {
                "doc_title": "信贷管理制度",
                "article_no": "第十五条",
                "clause_text": "本行禁止向关系人发放信用贷款",
                "subjects": ["本行"],
                "objects": ["信用贷款"],
                "biz_dims": ["信贷管理"],
                "action": "禁止",
            },
            "label": "完全符合",
            "confidence": 0.95,
            "reasoning": "内规完全落实外规要求，行为模态一致",
        },
        {
            "outer_clause": {
                "doc_title": "银行业监督管理法",
                "article_no": "第二十一条",
                "clause_text": "银行业金融机构应当按规定披露信息",
                "subjects": ["银行业金融机构"],
                "objects": ["信息"],
                "biz_dims": ["信息披露"],
                "action": "应当",
            },
            "inner_clause": {
                "doc_title": "信息披露制度",
                "article_no": "第八条",
                "clause_text": "本行每季度披露财务报告和风险信息",
                "subjects": ["本行"],
                "objects": ["财务报告", "风险信息"],
                "biz_dims": ["信息披露"],
                "action": "披露",
            },
            "label": "基本一致",
            "confidence": 0.85,
            "reasoning": "内规落实外规要求，但披露频率有具体规定",
        },
    ]

    demo_val_set = [
        {
            "outer_clause": {
                "doc_title": "商业银行法",
                "article_no": "第三十五条",
                "clause_text": "商业银行贷款应当对借款人的借款用途进行严格审查",
                "subjects": ["商业银行"],
                "objects": ["借款用途"],
                "biz_dims": ["信贷管理"],
                "action": "应当",
            },
            "inner_clause": {
                "doc_title": "贷款审查制度",
                "article_no": "第十二条",
                "clause_text": "贷款审批前必须核实借款用途真实性",
                "subjects": ["贷款审批部门"],
                "objects": ["借款用途"],
                "biz_dims": ["信贷管理"],
                "action": "必须",
            },
            "label": "完全符合",
            "confidence": 0.90,
            "reasoning": "内规严格对应外规要求",
        },
    ]

    result = {
        "train_set": demo_train_set,
        "val_set": demo_val_set,
        "failed_pairs": [],
        "stats": {
            "candidate_generation": {
                "after_filter": 100,
                "high_confidence": 50,
                "medium_confidence": 30,
            }
        },
    }

    # 转换为 SFT 格式
    convert_and_save_sft(result, config)

    # 打印统计
    print_stats(result)


def init_state(config_dict: dict) -> dict:
    """初始化工作流状态"""
    return {
        "config": config_dict,
        "raw_text": "",
        "clauses": [],
        "outer_clauses": [],
        "inner_clauses": [],
        "candidate_pairs": [],
        "candidate_idx": 0,
        "current_pair": None,
        "judgment_result": None,
        "review_result": None,
        "valid_pairs": [],
        "invalid_pairs": [],
        "qa_pairs": [],
        "failed_pairs": [],
        "train_set": [],
        "val_set": [],
        "train_pairs": [],
        "val_pairs": [],
        "test_pairs": [],
        "retry_count": 0,
        "stats": {},
    }


def run_rework_mode(config):
    """返工模式"""
    print("[SFT Pipeline] 返工模式...")

    output_dir = Path(config.get("data", {}).get("output_dir", "output"))
    failed_path = output_dir / "failed_pairs.jsonl"

    if not failed_path.exists():
        print("未找到 failed_pairs.jsonl，无需返工")
        return

    # 加载失败数据
    failed_pairs = []
    with open(failed_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                failed_pairs.append(json.loads(line))

    print(f"加载 {len(failed_pairs)} 条失败数据")

    # TODO: 实现返工逻辑
    print("返工模式尚未完全实现")


def resume_from_checkpoint(checkpoint_id: str, config):
    """从检查点恢复"""
    print(f"[SFT Pipeline] 从检查点 {checkpoint_id} 恢复...")

    checkpoint_dir = Path(config.get("checkpoint", {}).get("dir", "output/.checkpoints"))
    checkpoint_path = checkpoint_dir / f"{checkpoint_id}.json"

    if not checkpoint_path.exists():
        print(f"错误: 检查点文件不存在: {checkpoint_path}")
        return

    # 加载检查点
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        checkpoint_data = json.load(f)

    print(f"加载检查点: {checkpoint_data.get('timestamp', 'unknown')}")

    # TODO: 实现检查点恢复逻辑
    print("检查点恢复尚未完全实现")


def convert_and_save_sft(result: dict, config):
    """转换并保存 SFT 格式数据"""
    output_dir = Path(config.get("data", {}).get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 转换训练集
    train_set = result.get("train_set", result.get("train_pairs", []))
    train_sft = convert_dataset_to_sft(train_set)
    train_sft_path = output_dir / "train_sft.jsonl"
    with open(train_sft_path, "w", encoding="utf-8") as f:
        for item in train_sft:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # 转换验证集
    val_set = result.get("val_set", result.get("val_pairs", []))
    val_sft = convert_dataset_to_sft(val_set)
    val_sft_path = output_dir / "val_sft.jsonl"
    with open(val_sft_path, "w", encoding="utf-8") as f:
        for item in val_sft:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[SFT] 训练集: {len(train_sft)} 条 -> {train_sft_path}")
    print(f"[SFT] 验证集: {len(val_sft)} 条 -> {val_sft_path}")


def print_stats(result: dict):
    """打印统计信息"""
    stats = result.get("stats", {})
    print("\n" + "=" * 50)
    print("[统计报告]")
    print("=" * 50)

    if "candidate_generation" in stats:
        cg = stats["candidate_generation"]
        print(f"候选对生成: {cg.get('after_filter', 0)} 条")
        print(f"  - 高置信: {cg.get('high_confidence', 0)}")
        print(f"  - 中置信: {cg.get('medium_confidence', 0)}")

    train_set = result.get("train_set", result.get("train_pairs", []))
    val_set = result.get("val_set", result.get("val_pairs", []))
    failed_pairs = result.get("failed_pairs", [])

    print(f"训练集: {len(train_set)} 条")
    print(f"验证集: {len(val_set)} 条")
    print(f"失败数据: {len(failed_pairs)} 条")
    print("=" * 50)


if __name__ == "__main__":
    main()
