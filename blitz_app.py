import streamlit as st
import json
import os
from pathlib import Path
import google.generativeai as genai
from io import BytesIO
import base64
import openai
import edge_tts
import asyncio
import io

# ==================== System Instruction ====================
COACH_INSTRUCTION = """
You are a strict Reformed Theological Translation Consultant training Chinese students for cross-cultural missions (South Asia/Africa).
Your goal is to train students to translate Chinese (CUV) into precise ESV English, while equipping them with cultural sensitivity for KJV-loving mission fields.

**CORE EVALUATION LOGIC:**

1.  **Context is King (Theology):**
    * Evaluate based on the specific Bible Verse (e.g., Gen 17:7).
    * Distinguish between "Passable synonyms" and "Theological Precision".
    * *Example:* In Gen 15, "Cut (Karat)" is correct. In Gen 17, "Establish (Hēqîm)" is better.

2.  **The "Missionary Bridge" (KJV Handling):**
    * Your target audience respects the KJV. If the user uses a **KJV term** (e.g., "Holy Ghost", "Charity", "Seed", "Quickened") instead of the ESV target:
    * **Status:** 🟢 **GREEN (Pass)** or 🟡 **YELLOW (Valid Variant)** - DO NOT FAIL THEM.
    * **Feedback:** Acknowledge the KJV validity for the mission field, but gently guide back to ESV for academic precision.
    * *Example:* "Valid KJV term. 工场老信徒常用 'Holy Ghost'，但 ESV 为求清晰使用 'Holy Spirit'。"

3.  **The "Anti-Chinglish" Filter (Chinese Habit):**
    * Strictly monitor for "Chinglish" errors where students translate Chinese characters literally.
    * **Status:** 🔴 **RED (Fail)**.
    * *Example:* Translating "肉体" (Flesh/Sinful nature) as "Meat" or "Body".
    * *Example:* Translating "立约" (Make/Cut covenant) as "Build a contract".

4.  **Traffic Light System (Summary):**
    * 🟢 **GREEN (Pass):** Perfect ESV match OR Strong KJV variant.
    * 🟡 **YELLOW (Warning):** Passable word but missed nuance / Archaic KJV term.
    * 🔴 **RED (Fail):** Wrong meaning, Secular term (Contract), or Chinglish.

**FEEDBACK STYLE RULES (Crucial):**

* **Language:** Speak in **Chinese**, but keep Key Theological Terms in **English**.
* **Original Language:** ONLY cite Hebrew/Greek if it helps explain a nuanced distinction (e.g., distinguishing *Karat* vs *Qum*). Do NOT use it for simple vocabulary mistakes.
* **Anti-Redundancy:** The user sees the correct answer. Do NOT say "Correct answer is X". Instead, explain the **logic gap**.
    * *Bad:* "You said Make. The correct word is Establish."
    * *Good:* "这里用 Make 稍显软弱。Gen 17 是在确认旧约，原文 *Hēqîm* 强调 'Establish' (坚立) 而非新立。"
    * *Good (Chinglish):* "不要用 'Meat'。保罗神学中，'肉体'指罪性 (Flesh)，不是菜市场的肉。"

**Output Format:**
Return a JSON object: 
{
  "status": "pass" | "warning" | "fail", 
  "feedback": "Your concise, Chinese coaching comment (max 2 sentences)."
}
"""

# 页面配置
st.set_page_config(
    page_title="Theology Translation Blitz",
    page_icon="⚡",
    layout="wide"
)

# ==================== Session State Management ====================
if "current_queue" not in st.session_state:
    st.session_state.current_queue = []
if "failed_queue" not in st.session_state:
    st.session_state.failed_queue = []
if "current_batch" not in st.session_state:
    st.session_state.current_batch = []
if "results" not in st.session_state:
    st.session_state.results = []
if "api_key" not in st.session_state:
    st.session_state.api_key = None
if "selected_book" not in st.session_state:
    st.session_state.selected_book = None
if "use_proxy" not in st.session_state:
    st.session_state.use_proxy = True  # 默认使用 laozhang 中转服务
if "total_items" not in st.session_state:
    st.session_state.total_items = 0  # 总项目数

# ==================== Helper Functions ====================
@st.cache_data(show_spinner=False)
def get_audio_bytes(text, voice='en-US-ChristopherNeural', rate='-10%'):
    """
    Cached function to avoid repeated API calls/bandwidth usage.
    Generates audio and returns raw bytes in memory (no file I/O).
    """
    async def _gen():
        try:
            # Clean text: keep only ASCII printable characters
            import re
            if not text:
                raise ValueError("Text is empty")
            
            # Keep only ASCII characters (letters, numbers, spaces, punctuation)
            clean_text = re.sub(r'[^\x20-\x7E]', '', str(text))
            
            if not clean_text.strip():
                raise ValueError("Text contains no valid characters after cleaning")
            
            communicate = edge_tts.Communicate(clean_text, voice, rate=rate)
            # Write to memory buffer instead of file
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_fp.write(chunk["data"])
            mp3_fp.seek(0)  # Reset pointer to start
            return mp3_fp.getvalue()
        except Exception as e:
            # Re-raise with clean error message
            try:
                import re
                error_str = str(e)
                clean_error = re.sub(r'[^\x20-\x7E]', '', error_str)
                if not clean_error:
                    clean_error = "Unknown error"
                error_msg = clean_error
            except:
                error_msg = "Unknown error"
            raise Exception(f"Audio generation failed: {error_msg}")
    
    # Run async function in sync wrapper
    return asyncio.run(_gen())

def get_audio_mime_type(audio_data):
    """Get MIME type for audio data (handles both audio_input and file_uploader)"""
    if hasattr(audio_data, 'type') and audio_data.type:
        return audio_data.type
    elif hasattr(audio_data, 'name'):
        # File uploader - determine from file extension
        file_ext = audio_data.name.split('.')[-1].lower()
        mime_map = {
            'wav': 'audio/wav',
            'mp3': 'audio/mpeg',
            'm4a': 'audio/mp4',
            'webm': 'audio/webm',
            'ogg': 'audio/ogg'
        }
        return mime_map.get(file_ext, 'audio/wav')
    else:
        return "audio/webm"

def load_json_data(file_path):
    """Load JSON data from file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"加载数据文件失败: {str(e)}")
        return []

def get_available_books():
    """Get list of available JSON files in assets/bible_data/"""
    data_dir = Path("assets/bible_data")
    if not data_dir.exists():
        return []
    return [f.stem for f in data_dir.glob("*.json")]

def reset_game():
    """Reset all game state"""
    st.session_state.current_queue = []
    st.session_state.failed_queue = []
    st.session_state.current_batch = []
    st.session_state.results = []
    st.session_state.selected_book = None
    st.session_state.total_items = 0

def load_book_data(book_name):
    """Load data for selected book"""
    file_path = Path(f"assets/bible_data/{book_name}.json")
    if file_path.exists():
        data = load_json_data(file_path)
        # Reset queues and load new data
        st.session_state.current_queue = data.copy()
        st.session_state.failed_queue = []
        st.session_state.current_batch = []
        st.session_state.results = []
        st.session_state.total_items = len(data)  # 保存总数
        return True
    return False

def get_next_batch(batch_size=5):
    """
    Batching Logic:
    - Take the first 5 items from current_queue
    - If current_queue is empty, refill from failed_queue
    - Loop until mastery (failed_queue also empty)
    """
    # If current_queue is empty, refill from failed_queue
    if len(st.session_state.current_queue) == 0:
        if len(st.session_state.failed_queue) > 0:
            st.session_state.current_queue = st.session_state.failed_queue.copy()
            st.session_state.failed_queue = []
            st.info("🔄 主队列已空，从失败队列重新加载...")
        else:
            st.success("🎉 恭喜！您已掌握所有短语！")
            return []
    
    # Get next batch of 5 items
    batch = st.session_state.current_queue[:batch_size]
    st.session_state.current_batch = batch
    return batch

def process_results(ai_results):
    """
    Process AI grading results and update queues:
    - pass: Remove from current_queue (perfect match)
    - warning: Remove from current_queue (passable but note the nuance)
    - fail: Move to failed_queue (needs retry)
    """
    if not ai_results:
        return
    
    # Normalize status to lowercase for consistency
    for result in ai_results:
        status = result.get('status', '').lower()
        result['status'] = status
    
    # Remove processed items from current_queue
    processed_ids = [r.get('id') for r in ai_results]
    st.session_state.current_queue = [
        item for item in st.session_state.current_queue 
        if item['id'] not in processed_ids
    ]
    
    # Move failed items to failed_queue (only 'fail' status, not 'warning')
    for result in ai_results:
        status = result.get('status', '').lower()
        if status == 'fail':
            # Find the original item
            original_item = next(
                (item for item in st.session_state.current_batch 
                 if item['id'] == result.get('id')), 
                None
            )
            if original_item:
                st.session_state.failed_queue.append(original_item)

# ==================== Sidebar ====================
with st.sidebar:
    st.header("⚙️ 配置设置")
    
    # Use Proxy Option (默认启用)
    use_proxy = st.checkbox(
        "使用中转服务 (laozhang.ai)", 
        value=st.session_state.use_proxy,
        help="默认启用 laozhang.ai 中转服务，取消勾选使用官方 Google API"
    )
    st.session_state.use_proxy = use_proxy
    
    if use_proxy:
        st.info("🌐 使用中转服务: laozhang.ai")
        api_base_url = "https://api.laozhang.ai/v1"
    else:
        api_base_url = None
    
    # API Key Input
    api_key_input = st.text_input(
        "API Key",
        type="password",
        help="请输入您的 API Key（Google 或中转服务）",
        value=st.session_state.api_key or ""
    )
    if api_key_input:
        st.session_state.api_key = api_key_input
        if not use_proxy:
            # Only configure genai if not using proxy
            genai.configure(api_key=api_key_input)
    
    st.markdown("---")
    
    # Book Selector
    available_books = get_available_books()
    if available_books:
        selected_book = st.selectbox(
            "选择经卷",
            options=[""] + available_books,
            help="选择要训练的经卷数据",
            index=0 if st.session_state.selected_book not in available_books else available_books.index(st.session_state.selected_book) + 1
        )
        
        if selected_book and selected_book != st.session_state.selected_book:
            if load_book_data(selected_book):
                st.session_state.selected_book = selected_book
                st.success(f"✅ 已加载 {selected_book}")
    else:
        st.warning("⚠️ 未找到数据文件，请确保 assets/bible_data/ 目录存在")
    
    st.markdown("---")
    
    # Reset Game Button
    if st.button("🔄 重置游戏", use_container_width=True):
        reset_game()
        st.rerun()
    
    # Display Statistics
    st.markdown("---")
    st.subheader("📊 统计信息")
    
    # Calculate statistics
    total = st.session_state.total_items
    remaining = len(st.session_state.current_queue)
    failed = len(st.session_state.failed_queue)
    current_batch_size = len(st.session_state.current_batch)
    
    # Calculate completed (total - remaining - failed - current_batch)
    # But we need to account for items that passed and were removed
    # Completed = total - (remaining + failed + current_batch)
    completed = max(0, total - remaining - failed - current_batch_size) if total > 0 else 0
    
    if total > 0:
        st.metric("📚 总数", total)
        st.metric("✅ 已完成", completed, delta=f"{completed}/{total}")
        st.metric("⏳ 待测试", remaining)
        st.metric("🔄 需重试", failed)
        st.metric("📝 当前批次", current_batch_size)
        
        # Progress bar
        if total > 0:
            progress = completed / total
            st.progress(progress, text=f"进度: {completed}/{total} ({progress*100:.1f}%)")
    else:
        st.info("请先选择经卷开始训练")

# ==================== Main Interface ====================
st.title("⚡ Theology Translation Blitz")
st.markdown("**高速批量训练：中文（CUV）→ 英文（ESV）**")
st.markdown("---")

# Check if API key is set
if not st.session_state.api_key:
    st.warning("⚠️ 请在侧边栏输入 Google API Key 以开始使用")
    st.stop()

# Check if book is loaded
if not st.session_state.selected_book:
    st.info("📖 请在侧边栏选择经卷以开始训练")
    st.stop()

# Get current batch (5 items)
if not st.session_state.current_batch:
    batch = get_next_batch(5)
else:
    batch = st.session_state.current_batch

if not batch:
    st.stop()

# Display the batch
st.subheader(f"📝 当前批次 ({len(batch)} 个短语)")
st.markdown("**请按顺序用英文翻译以下中文短语：**")

# Display Chinese phrases in large, clean font
for i, item in enumerate(batch, 1):
    st.markdown(f"### {i}. {item['cn']}")

st.markdown("---")

# Audio Input - Support both recording and file upload
st.subheader("🎤 录音或上传音频")

# Create tabs for recording and file upload
tab1, tab2 = st.tabs(["🎙️ 录音", "📁 上传文件"])

audio_data = None

with tab1:
    audio_data = st.audio_input("点击开始录音（请依次翻译所有5个短语）", label_visibility="visible")

with tab2:
    uploaded_file = st.file_uploader(
        "选择音频文件上传",
        type=['wav', 'mp3', 'm4a', 'webm', 'ogg'],
        help="支持格式: WAV, MP3, M4A, WEBM, OGG"
    )
    if uploaded_file is not None:
        # Convert uploaded file to audio input format
        audio_data = uploaded_file
        # Determine audio format for playback
        file_ext = uploaded_file.name.split('.')[-1].lower() if hasattr(uploaded_file, 'name') else 'wav'
        mime_map = {
            'wav': 'audio/wav',
            'mp3': 'audio/mpeg',
            'm4a': 'audio/mp4',
            'webm': 'audio/webm',
            'ogg': 'audio/ogg'
        }
        audio_format = mime_map.get(file_ext, 'audio/wav')
        st.audio(uploaded_file, format=audio_format)
        st.success(f"✅ 已上传: {uploaded_file.name}")

# Process audio when submitted
if audio_data is not None:
    if st.button("🚀 提交评分", type="primary", use_container_width=True):
        with st.spinner("🤖 AI 正在评分..."):
            try:
                # Read audio bytes
                audio_bytes = audio_data.read()
                
                # Prepare expected targets list
                expected_targets = [f"ID {item['id']}: {item['en']}" for item in batch]
                targets_text = "\n".join(expected_targets)
                
                # Simplified prompt - system instruction already contains the rules
                # Create a numbered list for clarity
                items_list = "\n".join([f"{i+1}. ID {item['id']}: Chinese '{item['cn']}' → Expected ESV: '{item['en']}'" for i, item in enumerate(batch)])
                
                # Simple user prompt - system instruction handles the evaluation logic
                user_prompt = f"""Here is the audio recording. The user will translate 5 Chinese phrases to English in sequential order.

The 5 items in order:
{items_list}

Listen to the audio and for each item:
1. Transcribe EXACTLY what you hear (or "NO_AUDIO" if you hear nothing)
2. Evaluate using the theological coach rules from system instruction
3. Return JSON with status (pass/warning/fail), user_said, and feedback

Output JSON format:
[
  {{"id": 1, "status": "pass/warning/fail", "user_said": "exact transcription or 'NO_AUDIO'", "feedback": "coaching feedback"}},
  {{"id": 2, "status": "pass/warning/fail", "user_said": "exact transcription or 'NO_AUDIO'", "feedback": "coaching feedback"}},
  {{"id": 3, "status": "pass/warning/fail", "user_said": "exact transcription or 'NO_AUDIO'", "feedback": "coaching feedback"}},
  {{"id": 4, "status": "pass/warning/fail", "user_said": "exact transcription or 'NO_AUDIO'", "feedback": "coaching feedback"}},
  {{"id": 5, "status": "pass/warning/fail", "user_said": "exact transcription or 'NO_AUDIO'", "feedback": "coaching feedback"}}
]

⚠️ If audio is SILENT/EMPTY: ALL items must have user_said: "NO_AUDIO" and status: "fail"
⚠️ user_said MUST be what you actually HEAR, not the expected answer

Output ONLY valid JSON array."""

                # Initialize response_text
                response_text = None
                
                # Use laozhang.ai proxy or direct Google API
                if st.session_state.use_proxy:
                    # Use OpenAI SDK format for laozhang.ai
                    client = openai.OpenAI(
                        api_key=st.session_state.api_key,
                        base_url="https://api.laozhang.ai/v1"
                    )
                    
                    # Convert audio to base64
                    audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                    audio_mime_type = get_audio_mime_type(audio_data)
                    
                    # Use latest flash model: gemini-2.5-flash
                    model_name = "gemini-2.5-flash"
                    
                    # Call via OpenAI-compatible API with system instruction
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {
                                "role": "system",
                                "content": COACH_INSTRUCTION
                            },
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_prompt},
                                    {
                                        "type": "input_audio",
                                        "input_audio": {
                                            "data": audio_base64,
                                            "format": audio_mime_type.split('/')[-1]
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                    
                    # Extract response text
                    response_text = response.choices[0].message.content
                    
                else:
                    # Use direct Google API with latest flash model and system instruction
                    # Try gemini-2.0-flash-exp first, fallback to 1.5-pro, then 2.5-flash
                    model_name = None
                    try:
                        model = genai.GenerativeModel('gemini-2.0-flash-exp', system_instruction=COACH_INSTRUCTION)
                        model_name = 'gemini-2.0-flash-exp'
                    except:
                        try:
                            model = genai.GenerativeModel('gemini-1.5-pro', system_instruction=COACH_INSTRUCTION)
                            model_name = 'gemini-1.5-pro'
                        except:
                            # Fallback without system instruction
                            model = genai.GenerativeModel('gemini-2.5-flash')
                            model_name = 'gemini-2.5-flash'
                    
                    # Prepare audio file
                    audio_mime_type = get_audio_mime_type(audio_data)
                    audio_file = {
                        "mime_type": audio_mime_type,
                        "data": audio_bytes
                    }
                    
                    # Call Gemini API with simplified prompt (system instruction already set)
                    response = model.generate_content(
                        [user_prompt, audio_file]
                    )
                    response_text = response.text
                
                # Parse JSON response
                try:
                    # Extract JSON from response (already extracted if using proxy)
                    if not isinstance(response_text, str):
                        response_text = str(response_text)
                    response_text = response_text.strip()
                    # Remove markdown code blocks if present
                    if response_text.startswith("```"):
                        response_text = response_text.split("```")[1]
                        if response_text.startswith("json"):
                            response_text = response_text[4:]
                    response_text = response_text.strip()
                    
                    # Parse JSON
                    ai_results = json.loads(response_text)
                    
                    # Validate and fix results - detect if AI is copying expected answers
                    for result in ai_results:
                        item = next((i for i in batch if i['id'] == result.get('id')), None)
                        if item:
                            user_said = result.get('user_said', '').strip()
                            expected = item['en'].strip()
                            
                            # If user_said exactly matches expected AND status is PASS, 
                            # this might be AI copying (unless user actually said it correctly)
                            # We can't verify this, but we'll flag it for display
                            
                            # Normalize status to lowercase
                            status = result.get('status', '').lower()
                            result['status'] = status
                            
                            # If user_said is "NO_AUDIO" or similar, ensure status is fail
                            if user_said.upper() in ['NO_AUDIO', 'NOT SAID', 'MISSING', 'UNclear', '']:
                                result['status'] = 'fail'
                                result['user_said'] = '未录音'
                                if not result.get('feedback'):
                                    result['feedback'] = '未录音或未说出'
                            
                            # Flag suspicious cases where user_said matches expected exactly
                            # (could be correct, but could also be AI copying)
                            if user_said.lower() == expected.lower() and status in ['pass', 'warning']:
                                result['_suspicious'] = True  # Flag for potential copying
                    
                    st.session_state.results = ai_results
                    
                    # Process results and update queues
                    process_results(ai_results)
                    
                    # Display results
                    st.markdown("---")
                    st.subheader("📊 评分结果")
                    
                    # Create results dataframe
                    results_data = []
                    for result in ai_results:
                        # Find corresponding item
                        item = next((i for i in batch if i['id'] == result.get('id')), None)
                        if item:
                            # Normalize status for display
                            status_display = result.get('status', 'N/A')
                            if isinstance(status_display, str) and status_display != 'N/A':
                                status_display = status_display.upper()
                            results_data.append({
                                "ID": result.get('id'),
                                "中文": item['cn'],
                                "期望": item['en'],
                                "您的翻译": result.get('user_said', 'N/A'),
                                "状态": status_display,
                                "反馈": result.get('feedback', 'N/A')
                            })
                    
                    # Display results with audio feedback
                    import pandas as pd
                    
                    # Display each result with audio player
                    for idx, result in enumerate(ai_results):
                        # Find corresponding item
                        item = next((i for i in batch if i['id'] == result.get('id')), None)
                        if not item:
                            continue
                        
                        # Create container for each result
                        with st.container():
                            col1, col2 = st.columns([3, 1])
                            
                            with col1:
                                # Status badge (handle pass/warning/fail)
                                status = result.get('status', 'N/A').lower()
                                if status == 'pass':
                                    st.success(f"✅ ID {result.get('id')}: {item['cn']} → {item['en']}")
                                elif status == 'warning':
                                    st.warning(f"⚠️ ID {result.get('id')}: {item['cn']} → {item['en']}")
                                else:  # fail
                                    st.error(f"❌ ID {result.get('id')}: {item['cn']} → {item['en']}")
                                
                                # Display user's actual translation with validation
                                user_said = result.get('user_said', 'N/A')
                                expected = item['en']
                                
                                st.write(f"**您的翻译**: {user_said}")
                                st.write(f"**期望答案**: {expected}")
                                
                                # Check for NO_AUDIO or empty audio cases
                                if user_said.upper() in ['NO_AUDIO', '未录音', 'NOT SAID', 'MISSING', ''] or not user_said or user_said.strip() == '':
                                    st.error("❌ 未检测到录音内容 - 如果这是空录音，AI应该返回'NO_AUDIO'")
                                    # Force fail status if audio was empty
                                    status_lower = result.get('status', '').lower()
                                    if status_lower in ['pass', 'warning']:
                                        st.error("⚠️ 错误：空录音被标记为pass/warning，这是AI的bug")
                                
                                # Warn if suspicious (exact match might indicate AI copying)
                                elif result.get('_suspicious') or user_said.lower().strip() == expected.lower().strip():
                                    st.error("⚠️ 警告：检测到可能的问题。如果这是您实际说的内容，则正确；如果AI复制了标准答案，请重新测试或检查录音")
                                
                                st.write(f"**反馈**: {result.get('feedback', 'N/A')}")
                            
                            with col2:
                                # Generate and display audio for ESV target (using memory stream)
                                try:
                                    audio_bytes = get_audio_bytes(item['en'])
                                    if audio_bytes:
                                        st.audio(audio_bytes, format='audio/mp3')
                                        st.caption("标准 ESV 发音")
                                    else:
                                        st.info("音频生成中...")
                                except Exception as e:
                                    # Safely encode error message - remove all non-ASCII
                                    try:
                                        import re
                                        error_str = str(e)
                                        # Remove all non-ASCII characters including emojis
                                        error_msg = re.sub(r'[^\x20-\x7E]', '', error_str)
                                        if not error_msg:
                                            error_msg = "音频生成失败"
                                    except:
                                        error_msg = "音频生成失败"
                                    st.warning(f"音频生成失败: {error_msg}")
                            
                            st.markdown("---")
                    
                    # Also show summary table (only if we have data)
                    if results_data and len(results_data) > 0:
                        df = pd.DataFrame(results_data)
                        
                        # Check if '状态' column exists before styling
                        if '状态' in df.columns:
                            # Style the dataframe (handle PASS/WARNING/FAIL)
                            def color_status(val):
                                val_upper = str(val).upper()
                                if val_upper == 'PASS':
                                    return 'background-color: #90EE90'  # Light green
                                elif val_upper == 'WARNING':
                                    return 'background-color: #FFD700'  # Gold/Yellow
                                elif val_upper == 'FAIL':
                                    return 'background-color: #FFB6C1'  # Light red
                                return ''
                            
                            styled_df = df.style.applymap(color_status, subset=['状态'])
                            with st.expander("📋 查看详细表格"):
                                st.dataframe(styled_df, use_container_width=True, hide_index=True)
                        else:
                            # If '状态' column doesn't exist, show without styling
                            with st.expander("📋 查看详细表格"):
                                st.dataframe(df, use_container_width=True, hide_index=True)
                    else:
                        st.warning("没有结果数据可显示")
                    
                    # Show summary (handle pass/warning/fail)
                    pass_count = sum(1 for r in ai_results if r.get('status', '').lower() == 'pass')
                    warning_count = sum(1 for r in ai_results if r.get('status', '').lower() == 'warning')
                    fail_count = sum(1 for r in ai_results if r.get('status', '').lower() == 'fail')
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("✅ 通过", pass_count)
                    with col2:
                        st.metric("⚠️ 警告", warning_count)
                    with col3:
                        st.metric("❌ 失败", fail_count)
                    
                except json.JSONDecodeError as e:
                    # Safely encode error message
                    error_msg = str(e).encode('utf-8', errors='replace').decode('utf-8')
                    st.error(f"JSON 解析错误: {error_msg}")
                    st.code(response_text)
                    st.info("请检查 AI 响应格式")
                except Exception as e:
                    # Safely encode error message
                    error_msg = str(e).encode('utf-8', errors='replace').decode('utf-8')
                    st.error(f"处理结果时出错: {error_msg}")
                    st.code(response_text)
                    
            except Exception as e:
                # Safely encode error message to avoid encoding issues
                try:
                    import re
                    # Remove emojis and non-ASCII characters from error message
                    error_str = str(e)
                    # Keep only ASCII printable characters and common Chinese characters
                    # First try to preserve Chinese characters
                    try:
                        error_msg = error_str.encode('utf-8', errors='replace').decode('utf-8')
                        # Remove emojis
                        error_msg = re.sub(r'[^\x00-\x7F\u4e00-\u9fff\s]', '', error_msg)
                    except:
                        # Fallback: ASCII only
                        error_msg = re.sub(r'[^\x20-\x7E]', '', error_str)
                    if not error_msg.strip():
                        error_msg = "处理音频时发生未知错误"
                except:
                    error_msg = "处理音频时发生未知错误"
                st.error(f"处理音频时出错: {error_msg}")
                st.info("请检查：\n1. API Key 是否正确\n2. 网络连接是否正常\n3. 音频格式是否支持")

# Next Batch Button
if st.session_state.results:
    st.markdown("---")
    if st.button("➡️ 下一批次", type="primary", use_container_width=True):
        st.session_state.current_batch = []
        st.session_state.results = []
        st.rerun()

# Footer
st.markdown("---")
st.caption("💡 提示：通过的短语会从队列移除，失败的会加入重试队列，直到全部掌握")

