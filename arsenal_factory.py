import os
import json
import time
import re
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import OpenAI  # ✅ 换用 OpenAI 库来连接中转站

# 加载 .env
load_dotenv()

# ================= 配置区域 =================
API_KEY = os.getenv("GEMINI_API_KEY")
BASE_URL = os.getenv("GEMINI_BASE_URL", "https://api.laozhang.ai/v1") # ✅ 适配老张接口

BLUEPRINT_FILE = "assets/bible_data/blueprint_strong_verbs.json"
OUTPUT_DIR = "assets/bible_data"

TARGET_COUNT_PER_BOOK = 30
BATCH_SIZE = 10

# ================= 初始化 =================
if not API_KEY:
    raise ValueError("❌ Error: GEMINI_API_KEY not found in .env")

print(f"🔌 Connecting to: {BASE_URL}")

# ✅ 初始化 OpenAI 客户端 (但调用的是 Gemini 模型)
client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

# 模型名称
MODEL_NAME = "gemini-2.5-flash" 

# ================= 辅助函数：AI 调用封装 =================

def call_ai_json(prompt: str, temperature: float = 0.7) -> List[Dict]:
    """
    发送请求并解析 JSON，自带 Markdown 清理功能
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a strict JSON generator. Output only valid JSON lists."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            # max_tokens=4096, # 根据需要调整
        )
        
        content = response.choices[0].message.content
        
        # 🧹 清洗数据：有些模型喜欢加 ```json ... ```，必须去掉
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```', '', content)
        content = content.strip()
        
        return json.loads(content)
        
    except json.JSONDecodeError:
        print("      ⚠️ JSON Decode Error. AI output might be malformed.")
        return []
    except Exception as e:
        print(f"      ⚠️ API Error: {e}")
        return []

# ================= 核心逻辑 (逻辑保持不变) =================

def load_blueprint():
    with open(BLUEPRINT_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_book_data(book_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    book_name = book_data['book']
    print(f"\n📘 Processing Book: {book_name}...")
    
    final_items = []
    seen_refs = set()
    
    # --- PART 1: 强动词特训 ---
    strong_verbs = book_data.get('strong_verb_focus', [])
    if strong_verbs:
        print(f"   🔥 Processing {len(strong_verbs)} high-priority Strong Verbs...")
        
        prompt_sv = f"""
        You are a Theological Translation Data Generator.
        Expand these specific Strong Verb focuses into JSON cards.
        
        INPUT: {json.dumps(strong_verbs, ensure_ascii=False)}
        
        REQUIREMENTS:
        1. Output strictly valid JSON list.
        2. 'trap': Use the 'weak_trap' provided.
        3. 'sentence_context': Provide full ESV context.
        4. 'nuance_note': Use the provided nuance. 
           ⚠️ IMPORTANT: Inside brackets, use English terms or Hebrew/Greek (e.g., '立约 (Covenant)'). NEVER use Pinyin.
        """
        
        # 调用封装好的函数
        sv_items = call_ai_json(prompt_sv, temperature=0.7)
        
        if sv_items:
            for item in sv_items:
                ref_clean = item.get('ref', '').strip()
                if ref_clean:
                    seen_refs.add(ref_clean)
                final_items.append(item)
            print(f"   ✅ Strong Verbs added. Count: {len(final_items)}")
        else:
            print("   ⚠️ No items returned for Strong Verbs.")

    # --- PART 2: 广度挖掘 ---
    
    chinglish_traps = book_data.get('chinglish_traps', {})
    key_verbs = book_data.get('key_verbs', [])
    theme = book_data.get('theme', "")
    
    retry_count = 0
    
    while len(final_items) < TARGET_COUNT_PER_BOOK and retry_count < 3:
        needed = TARGET_COUNT_PER_BOOK - len(final_items)
        current_batch = min(needed, BATCH_SIZE)
        
        forbidden_refs_str = ", ".join(list(seen_refs))
        if len(forbidden_refs_str) > 1500:
            forbidden_refs_str = "Many verses already used. Find UNIQUE ones."
            
        print(f"   ⛏️ Mining batch of {current_batch}... (Avoid refs: {len(seen_refs)})")
        
        # 动态温度
        current_temp = 0.7 + (len(final_items) / TARGET_COUNT_PER_BOOK) * 0.2
        if current_temp > 1.3: current_temp = 1.3 # OpenAI 温度上限通常较高，但保守一点

        prompt_gen = f"""
        Role: Theological Translation Generator.
        Goal: Generate {current_batch} UNIQUE practice items for the book of {book_name}.
        Theme: {theme}
        
        ⛔ CRITICAL CONSTRAINT (DUPLICATE PREVENTION):
        **DO NOT USE these references:** [{forbidden_refs_str}]
        You MUST find different verses.
        
        STRATEGY:
        1. Scan the ENTIRE book.
        2. Use these TRAPS: {json.dumps(chinglish_traps, ensure_ascii=False)}
        3. Use these KEY TERMS: {json.dumps(key_verbs, ensure_ascii=False)}
        4. Focus on **Strong Verbs** vs **Weak Verbs**.
        
        OUTPUT FORMAT (JSON List):
        [
          {{
            "ref": "Chapter:Verse",
            "phrase_cn": "Chinese",
            "phrase_en": "ESV",
            "sentence_context": "Full context",
            "key_term": "Strong Verb/Term",
            "trap": "Chinglish Trap",
            "nuance_note": "Brief explanation. ⛔ STRICTLY FORBIDDEN: Do NOT use Pinyin in brackets. Use English or Hebrew/Greek. Example: '因为约 (Covenant)'."
          }}
        ]
        """
        
        # 调用封装好的函数
        batch_items = call_ai_json(prompt_gen, temperature=current_temp)
        
        valid_batch = []
        duplicates = 0
        
        if batch_items:
            for item in batch_items:
                this_ref = item.get('ref', '').strip()
                is_dup = False
                
                # 模糊匹配
                for seen in seen_refs:
                    if (seen in this_ref) or (this_ref in seen and len(this_ref) > 3):
                        is_dup = True
                        break
                
                if not is_dup and "phrase_cn" in item:
                    valid_batch.append(item)
                    seen_refs.add(this_ref)
                else:
                    duplicates += 1
            
            if len(valid_batch) > 0:
                final_items.extend(valid_batch)
                print(f"      -> Success! Added {len(valid_batch)} unique items. (Skipped {duplicates} dups)")
                retry_count = 0 
            else:
                print("      -> Batch yielded only duplicates. Retrying...")
                retry_count += 1
        else:
            print("      -> Batch failed (Empty/Error). Retrying...")
            retry_count += 1
            time.sleep(1)

    # 添加 ID
    for idx, item in enumerate(final_items):
        item['id'] = idx + 1
        
    return final_items

# ================= 主程序 =================

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    blueprint = load_blueprint()
    print(f"🚀 Starting Factory (Laozhang Adapter). Target: {TARGET_COUNT_PER_BOOK}/book.")
    
    for book_data in blueprint:
        items = generate_book_data(book_data)
        
        filename = f"{OUTPUT_DIR}/{book_data['book']}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            
        print(f"💾 Saved {len(items)} items to {filename}")
        time.sleep(1) 

if __name__ == "__main__":
    main()