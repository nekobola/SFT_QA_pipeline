#!/usr/bin/env python
"""并发版 SFT 数据生成 - 使用线程池加速 LLM 调用"""
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from utils.sft_converter import convert_dataset_to_sft
from workflow.nodes_concurrent import (
    node_parse_clauses,
    node_filter_candidates,
    node_batch_process,
    node_split_dataset,
    node_persist,
)


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


def run_concurrent_pipeline(config):
    """运行并发版工作流"""
    print("=" * 50, flush=True)
    print("[SFT Pipeline - Concurrent] 开始运行...", flush=True)
    print("=" * 50, flush=True)

    # 初始化状态
    state = init_state(config.to_dict())

    # 1. 解析条款
    print("\n[Step 1/5] 解析条款...", flush=True)
    result = node_parse_clauses(state)
    state.update(result)

    # 2. 筛选候选对
    print("\n[Step 2/5] 筛选候选对...", flush=True)
    result = node_filter_candidates(state)
    state.update(result)

    # 3. 批量并发处理
    print("\n[Step 3/5] 批量并发处理...", flush=True)
    result = node_batch_process(state)
    state.update(result)

    # 4. 划分数据集
    print("\n[Step 4/5] 划分数据集...", flush=True)
    result = node_split_dataset(state)
    state.update(result)

    # 5. 持久化
    print("\n[Step 5/5] 持久化存储...", flush=True)
    result = node_persist(state)
    state.update(result)

    # 打印统计
    print_stats(state)


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

    # 新增：打印标签分布
    if "output_stats" in stats:
        os = stats["output_stats"]
        print(f"\n[标签分布]")
        original_count = os.get("train_original", 0)
        conflict_count = os.get("train_conflict", 0)
        print(f"  原始QA: {original_count} 条")
        print(f"  冲突QA: {conflict_count} 条")
        print(f"  标签统计: {os.get('label_distribution', {})}")

    print("=" * 50)


def main():
    """主入口"""
    import argparse
    parser = argparse.ArgumentParser(description="并发版 SFT 数据生成")
    parser.add_argument("--config", type=str, default="config.yaml", help="配置文件路径")
    parser.add_argument("--candidates", type=int, default=0, help="处理的候选对数量（0 表示不限制）")
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 覆盖候选对数量限制
    if args.candidates > 0:
        config._data["target"]["max_candidates_to_process"] = args.candidates

    # 运行
    run_concurrent_pipeline(config)


if __name__ == "__main__":
    main()
