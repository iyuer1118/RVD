#!/usr/bin/env python3
"""
分析知识库 segments.json 中的重复文档情况。
"""
import json
import os
from collections import defaultdict
from difflib import SequenceMatcher

SEGS_PATH = os.getenv("RAG_SEGMENTS_PATH", os.path.join(os.path.dirname(__file__), "knowledge_bases", os.getenv("RAG_KB_NAME", "papers"), "segments.json"))

# ── 1. 加载数据 ──────────────────────────────────────────────
segments = []
with open(SEGS_PATH, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            segments.append(json.loads(line))

print(f"总段落数: {len(segments)}")

# ── 2. 按 source 分组统计 ────────────────────────────────────
source_segments = defaultdict(list)
for seg in segments:
    source_segments[seg["source"]].append(seg["text"])

print(f"唯一 source 数: {len(source_segments)}")
print()

# 按 source 排序，打印统计
sorted_sources = sorted(source_segments.items(), key=lambda x: -len(x[1]))
print("=" * 80)
print("各 source 段落数统计:")
print("=" * 80)
for src, segs in sorted_sources:
    print(f"  {len(segs):3d} 段  {src}")
print()

# ── 3. 基于文件名的重复检测 ──────────────────────────────────
def normalize_filename(name):
    """提取论文标题关键词用于比较"""
    # 去掉 .pdf 后缀
    name = name.replace(".pdf", "")
    parts = name.split("_")
    if len(parts) >= 2:
        # 取标题部分（通常是第二部分）
        title = parts[1] if len(parts) > 1 else parts[0]
        return title.lower().strip()
    return name.lower().strip()

def extract_title_keywords(name):
    """从文件名中提取标题关键词"""
    name = name.replace(".pdf", "")
    parts = name.split("_")
    if len(parts) >= 2:
        title = "_".join(parts[1:-2]) if len(parts) > 3 else parts[1]
        return title.lower().strip()
    return name.lower().strip()

# ── 4. 基于内容的重复检测 ────────────────────────────────────
def get_prefix(text, n=100):
    """获取文本前 n 个字符"""
    return text.strip()[:n]

def compute_content_overlap(texts_a, texts_b, prefix_len=100):
    """
    计算两组文本的内容重叠度。
    返回：(a中与b匹配的比例, b中与a匹配的比例, 匹配的a数量, 匹配的b数量)
    """
    prefixes_a = {get_prefix(t, prefix_len) for t in texts_a}
    prefixes_b = {get_prefix(t, prefix_len) for t in texts_b}
    
    # 去掉空前缀
    prefixes_a.discard("")
    prefixes_b.discard("")
    
    if not prefixes_a or not prefixes_b:
        return 0.0, 0.0, 0, 0
    
    common = prefixes_a & prefixes_b
    
    overlap_a = len(common) / len(prefixes_a) if prefixes_a else 0
    overlap_b = len(common) / len(prefixes_b) if prefixes_b else 0
    
    return overlap_a, overlap_b, len(common), len(prefixes_a | prefixes_b)

def compute_similarity(name_a, name_b):
    """计算两个文件名的相似度"""
    return SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()

# ── 5. 查找重复组 ────────────────────────────────────────────
sources = list(source_segments.keys())
n = len(sources)

# 存储所有可疑的重复对
duplicate_pairs = []

print("=" * 80)
print("正在分析内容重复情况...")
print("=" * 80)

for i in range(n):
    for j in range(i + 1, n):
        src_a = sources[i]
        src_b = sources[j]
        
        texts_a = source_segments[src_a]
        texts_b = source_segments[src_b]
        
        # 先检查文件名相似度，快速跳过明显不同的
        name_sim = compute_similarity(src_a, src_b)
        
        # 内容重叠检测
        overlap_a, overlap_b, common_count, total_unique = compute_content_overlap(texts_a, texts_b)
        
        # 判定重复条件：
        # 1) 任一 source 中超过 50% 段落前缀与另一 source 匹配
        # 2) 或者文件名相似度很高（>0.7）且有一定内容重叠
        is_duplicate = False
        if overlap_a > 0.5 or overlap_b > 0.5:
            is_duplicate = True
        elif name_sim > 0.7 and (overlap_a > 0.2 or overlap_b > 0.2):
            is_duplicate = True
        elif common_count >= 3 and (overlap_a > 0.3 or overlap_b > 0.3):
            is_duplicate = True
            
        if is_duplicate:
            max_overlap = max(overlap_a, overlap_b)
            min_overlap = min(overlap_a, overlap_b)
            avg_overlap = (overlap_a + overlap_b) / 2
            duplicate_pairs.append({
                "src_a": src_a,
                "src_b": src_b,
                "segs_a": len(texts_a),
                "segs_b": len(texts_b),
                "overlap_a": overlap_a,
                "overlap_b": overlap_b,
                "common_prefixes": common_count,
                "name_similarity": name_sim,
                "avg_overlap": avg_overlap,
            })

print(f"发现 {len(duplicate_pairs)} 对可疑重复文档\n")

# ── 6. 合并为重复组 ──────────────────────────────────────────
# 使用并查集
parent = {}
def find(x):
    if x not in parent:
        parent[x] = x
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x

def union(x, y):
    rx, ry = find(x), find(y)
    if rx != ry:
        parent[rx] = ry

for pair in duplicate_pairs:
    union(pair["src_a"], pair["src_b"])

groups = defaultdict(set)
for src in sources:
    r = find(src)
    if r in parent:  # 只包含有配对的
        # 检查这个 source 是否在任一 duplicate pair 中
        pass

# 重新用更简单的方法分组
groups = defaultdict(set)
for pair in duplicate_pairs:
    groups[find(pair["src_a"])].add(pair["src_a"])
    groups[find(pair["src_b"])].add(pair["src_b"])

# 过滤掉只有单个成员的组（不应该发生但以防万一）
groups = {k: v for k, v in groups.items() if len(v) >= 2}

print("=" * 80)
print(f"重复文档分组（共 {len(groups)} 组）")
print("=" * 80)

group_list = []
for gid, (root, members) in enumerate(sorted(groups.items()), 1):
    members = sorted(members)
    
    # 找出组内所有配对的最高重叠度
    max_avg_overlap = 0
    for pair in duplicate_pairs:
        if pair["src_a"] in members and pair["src_b"] in members:
            max_avg_overlap = max(max_avg_overlap, pair["avg_overlap"])
    
    # 收集每个成员的段落数
    member_info = []
    for m in members:
        member_info.append({
            "name": m,
            "segments": len(source_segments[m]),
        })
    
    group_list.append({
        "group_id": gid,
        "members": member_info,
        "max_avg_overlap": max_avg_overlap,
    })

# ── 7. 输出结果 ──────────────────────────────────────────────
print()
for g in group_list:
    gid = g["group_id"]
    members = g["members"]
    
    print(f"┌─────────────────────────────────────────────────────────────────────────────")
    print(f"│ 重复组 #{gid}  |  最高平均重叠度: {g['max_avg_overlap']:.1%}")
    print(f"├─────────────────────────────────────────────────────────────────────────────")
    
    # 按段落数排序
    members.sort(key=lambda x: -x["segments"])
    
    for idx, m in enumerate(members):
        role = "✅ 建议保留" if idx == 0 else "❌ 建议删除"
        print(f"│  {role}  |  {m['segments']:3d} 段  |  {m['name']}")
    
    # 输出组内详细对比
    print(f"├─────────────────────────────────────────────────────────────────────────────")
    for pair in duplicate_pairs:
        if pair["src_a"] in {m["name"] for m in members} and pair["src_b"] in {m["name"] for m in members}:
            print(f"│  对比: {pair['src_a'][:50]}...")
            print(f"│    vs: {pair['src_b'][:50]}...")
            print(f"│        A重叠度={pair['overlap_a']:.1%}  B重叠度={pair['overlap_b']:.1%}  "
                  f"共同前缀数={pair['common_prefixes']}  文件名相似度={pair['name_similarity']:.2f}")
    print(f"└─────────────────────────────────────────────────────────────────────────────")
    print()

# ── 8. 汇总统计 ──────────────────────────────────────────────
total_duplicate_sources = sum(len(g["members"]) for g in group_list)
total_duplicate_segments = sum(
    m["segments"] for g in group_list for m in g["members"]
)
segments_to_remove = sum(
    m["segments"] for g in group_list for m in g["members"][1:]
)

print()
print("=" * 80)
print("汇总统计")
print("=" * 80)
print(f"  重复组数量:              {len(group_list)}")
print(f"  涉及重复的 source 数:    {total_duplicate_sources}")
print(f"  涉及重复的段落总数:      {total_duplicate_segments}")
print(f"  建议删除的 source 数:    {total_duplicate_sources - len(group_list)}")
print(f"  建议删除的段落数:        {segments_to_remove}")
print(f"  清理后剩余 source 数:    {len(source_segments) - (total_duplicate_sources - len(group_list))}")
print(f"  清理后剩余段落数:        {len(segments) - segments_to_remove}")
print()

# ── 9. 导出详细结果到 JSON ───────────────────────────────────
output = {
    "summary": {
        "total_segments": len(segments),
        "total_sources": len(source_segments),
        "duplicate_groups": len(group_list),
        "duplicate_sources": total_duplicate_sources,
        "segments_to_remove": segments_to_remove,
    },
    "groups": [],
}

for g in group_list:
    group_data = {
        "group_id": g["group_id"],
        "max_avg_overlap": g["max_avg_overlap"],
        "recommendation": {
            "keep": g["members"][0]["name"],
            "remove": [m["name"] for m in g["members"][1:]],
        },
        "members": g["members"],
        "pair_details": [],
    }
    for pair in duplicate_pairs:
        if pair["src_a"] in {m["name"] for m in g["members"]} and pair["src_b"] in {m["name"] for m in g["members"]}:
            group_data["pair_details"].append(pair)
    output["groups"].append(group_data)

output_path = "knowledge_bases/papers/duplicate_analysis.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"详细分析结果已保存到: {output_path}")
