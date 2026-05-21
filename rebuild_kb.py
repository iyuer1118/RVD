#!/usr/bin/env python3
"""
重建知识库：从PDF提取文本 → 分段 → 生成嵌入
"""
import os
import json
import sys
import glob

# PDF提取
try:
    import PyPDF2
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

def extract_pdf_text(filepath):
    """从PDF提取文本"""
    if not HAS_PYPDF:
        print(f"  Warning: PyPDF2 not installed, skipping {filepath}")
        return ""
    text = ""
    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as e:
        print(f"  Error reading {filepath}: {e}")
    return text

def extract_file_text(filepath):
    """根据文件类型提取文本"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        return extract_pdf_text(filepath)
    elif ext in ('.txt', '.md'):
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    elif ext == '.json':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return json.dumps(json.load(f), ensure_ascii=False, indent=2)
    return ""

def split_text(text, max_length=800, overlap=150):
    """按段落/句子分割文本"""
    if not text.strip():
        return []
    
    # 先按段落分割
    paragraphs = text.split('\n\n')
    chunks = []
    current = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) > max_length:
            if current:
                chunks.append(current.strip())
            # 如果单段落超长，按句子再分
            if len(para) > max_length:
                sentences = para.replace('. ', '.\n').replace('? ', '?\n').replace('! ', '!\n').split('\n')
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) > max_length:
                        if current:
                            chunks.append(current.strip())
                        current = sent
                    else:
                        current += " " + sent
            else:
                current = para
        else:
            current += "\n\n" + para
    
    if current.strip():
        chunks.append(current.strip())
    
    # 过滤太短的
    chunks = [c for c in chunks if len(c) > 30]
    return chunks

def main():
    base_dir = os.path.abspath(os.getenv("RAG_BASE_DIR", os.path.dirname(__file__)))
    kb_name = os.getenv("RAG_KB_NAME", "RVD")
    ref_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base_dir, "reference")
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(base_dir, "knowledge_bases", kb_name)
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 收集所有文档
    files = []
    for ext in ('*.pdf', '*.txt', '*.md'):
        files.extend(glob.glob(os.path.join(ref_dir, ext)))
    files.sort()
    
    print(f"找到 {len(files)} 个文档")
    
    # 提取并分割
    all_segments = []
    for i, f in enumerate(files):
        fname = os.path.basename(f)
        print(f"[{i+1}/{len(files)}] 处理: {fname}")
        text = extract_file_text(f)
        if not text.strip():
            print(f"  跳过（无文本）")
            continue
        chunks = split_text(text)
        for chunk in chunks:
            all_segments.append({
                'text': chunk,
                'source': fname
            })
        print(f"  提取 {len(chunks)} 个段落")
    
    print(f"\n总共 {len(all_segments)} 个段落")
    
    # 保存干净的segments
    seg_file = os.path.join(output_dir, 'segments.json')
    with open(seg_file, 'w', encoding='utf-8') as f:
        for seg in all_segments:
            f.write(json.dumps(seg, ensure_ascii=False) + '\n')
    
    # 保存metadata
    meta = {
        'name': 'ollama_bge_m3',
        'description': 'RecurringVul 二进制代码相似性检测相关论文和文档（重建版）',
        'model': 'bge-m3',
        'created': '2026-05-11',
        'segments': len(all_segments)
    }
    with open(os.path.join(output_dir, 'metadata.json'), 'w') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    print(f"segments已保存到 {seg_file}")
    print("接下来需要运行嵌入生成...")

if __name__ == '__main__':
    main()
