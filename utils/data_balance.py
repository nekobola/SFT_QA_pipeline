"""数据平衡模块 - 按目标分布重新采样"""
import json
import random
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Optional


# 默认目标分布
DEFAULT_TARGET_DISTRIBUTION = {
    "完全符合": 0.20,
    "基本一致": 0.30,
    "部分冲突": 0.25,
    "直接冲突": 0.15,
    "无关": 0.10,
}


def load_jsonl(file_path: str) -> list[dict]:
    """加载 JSONL 文件"""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def save_jsonl(data: list[dict], file_path: str):
    """保存 JSONL 文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def get_label(item: dict) -> str:
    """从数据项中提取标签"""
    output = json.loads(item.get('output', '{}'))
    return output.get('label', '未知')


def balance_dataset(
    data: list[dict],
    target_distribution: dict[str, float],
    total_samples: Optional[int] = None,
    oversample_minority: bool = False,
    random_seed: int = 42,
) -> list[dict]:
    """
    按目标分布重新采样数据

    Args:
        data: 原始数据
        target_distribution: 目标分布 {label: ratio}
        total_samples: 目标总样本数，None 则保持原始数量
        oversample_minority: 是否对少数类过采样
        random_seed: 随机种子

    Returns:
        平衡后的数据
    """
    random.seed(random_seed)

    # 按标签分组
    by_label = defaultdict(list)
    for item in data:
        label = get_label(item)
        by_label[label].append(item)

    # 打印原始分布
    print("\n[原始分布]")
    total_original = len(data)
    for label in target_distribution.keys():
        count = len(by_label.get(label, []))
        pct = count / total_original * 100 if total_original > 0 else 0
        print(f"  {label}: {count} ({pct:.1f}%)")

    # 计算目标数量
    if total_samples is None:
        total_samples = total_original

    target_counts = {}
    for label, ratio in target_distribution.items():
        target_counts[label] = int(total_samples * ratio)

    # 调整总数（四舍五入误差）
    diff = total_samples - sum(target_counts.values())
    if diff != 0:
        # 将差额加到最大的类别
        max_label = max(target_counts, key=target_counts.get)
        target_counts[max_label] += diff

    print(f"\n[目标分布] 总样本数: {total_samples}")
    for label in target_distribution.keys():
        print(f"  {label}: {target_counts[label]} ({target_distribution[label]*100:.0f}%)")

    # 采样
    balanced = []
    stats = {"sampled": {}, "oversampled": {}}

    for label, target_n in target_counts.items():
        available = by_label.get(label, [])

        if len(available) >= target_n:
            # 样本充足，随机采样
            sampled = random.sample(available, target_n)
            stats["sampled"][label] = target_n
        else:
            # 样本不足
            if oversample_minority:
                # 过采样：重复采样
                sampled = available.copy()
                remaining = target_n - len(available)
                while remaining > 0:
                    n_to_add = min(remaining, len(available))
                    sampled.extend(random.sample(available, n_to_add))
                    remaining -= n_to_add
                stats["oversampled"][label] = target_n - len(available)
            else:
                # 不够就全部使用
                sampled = available
                stats["sampled"][label] = len(available)
                print(f"  [警告] {label} 样本不足: {len(available)} < {target_n}")

        balanced.extend(sampled)

    # 打印统计
    print(f"\n[采样统计]")
    print(f"  成功采样: {sum(stats['sampled'].values())}")
    if stats["oversampled"]:
        print(f"  过采样补充: {sum(stats['oversampled'].values())}")

    # 打印最终分布
    print(f"\n[最终分布]")
    final_by_label = defaultdict(int)
    for item in balanced:
        final_by_label[get_label(item)] += 1

    for label in target_distribution.keys():
        count = final_by_label.get(label, 0)
        pct = count / len(balanced) * 100 if balanced else 0
        print(f"  {label}: {count} ({pct:.1f}%)")

    # 打乱顺序
    random.shuffle(balanced)

    return balanced


def main():
    parser = argparse.ArgumentParser(description="数据平衡工具")
    parser.add_argument("--input", type=str, required=True, help="输入 JSONL 文件路径")
    parser.add_argument("--output", type=str, required=True, help="输出 JSONL 文件路径")
    parser.add_argument("--total", type=int, default=None, help="目标总样本数")
    parser.add_argument("--oversample", action="store_true", help="对少数类过采样")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    # 加载数据
    print(f"[加载] {args.input}")
    data = load_jsonl(args.input)
    print(f"  共 {len(data)} 条数据")

    # 平衡数据
    balanced = balance_dataset(
        data,
        DEFAULT_TARGET_DISTRIBUTION,
        total_samples=args.total,
        oversample_minority=args.oversample,
        random_seed=args.seed,
    )

    # 保存结果
    save_jsonl(balanced, args.output)
    print(f"\n[保存] {args.output}")
    print(f"  共 {len(balanced)} 条数据")


if __name__ == "__main__":
    main()
