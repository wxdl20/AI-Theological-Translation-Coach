import streamlit as st
import json
import os
import random
import base64
import edge_tts
import asyncio
import re
import tempfile
import html
from dotenv import load_dotenv
from openai import OpenAI

# ==================== System Instruction ====================
# 基础教练指令（所有模式共享）
BASE_COACH_INSTRUCTION = """
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

**COMPARISON-BASED COACHING (Core Function):**

You MUST compare the user's transcribed speech with the ESV target word-by-word and phrase-by-phrase.

1. **Precise Comparison:**
   * Identify EXACT differences: missing words, wrong word choice, word order, grammar errors.
   * Focus on the KEY TERM first, then sentence structure.

2. **Concise & Actionable Feedback:**
   * **Word Count:** Maximum 2 sentences (ideally 1 sentence). Be BRIEF but PRECISE.
   * **Focus on Improvement:** Don't just point out errors. Explain WHY the ESV choice is better and HOW to improve.
   * **Pattern Recognition:** If the error suggests a deeper issue (e.g., always using weak verbs), hint at the pattern.
   
3. **Examples of Good Feedback:**
   * *Bad (too long):* "You said 'make' but the correct answer is 'establish'. In Hebrew, the word Hēqîm means to establish or confirm something that already exists, not to create something new. So you should use 'establish' instead of 'make'."
   * *Good (concise & actionable):* "用 'Establish' 替代 'Make'。这里强调坚立旧约，不是新立。"
   * *Good (pattern-focused):* "避免通用动词 'Give'。神学语境中，'Present' 更精准，强调主动献上。"

4. **Feedback Priority:**
   * If KEY TERM is wrong → Focus on theological precision.
   * If structure is wrong → Focus on English syntax.
   * If both are wrong → Focus on KEY TERM first.

**Output Format:**
Return a JSON object: 
{
  "status": "pass" | "warning" | "fail", 
  "user_said": "exact transcription from audio",
  "feedback": "Markdown in Chinese with THREE ultra-short lines: '### 1. 神学核心 (Theology)：...'; '### 2. 演绎表现 (Delivery)：...'; '### 3. 成长聚焦 (Growth)：...'. Each line ≤ 16 Chinese characters, keep key theological terms in English."
}
"""

# 模式特定的系统指令
MODE_INSTRUCTIONS = {
    "🎙️ 讲台口译 (Pulpit)": """你是一位在跨文化宣教工场服侍多年的**资深讲台口译导师**。
重点评估：
1. **强动词气势**: 拒绝软绵绵的词 (如 Give vs Present)。
2. **语音语调**: 用词力度和权威感。
3. **反中式搭配**: 严禁 Chinglish。
风格：激情、直接、像讲道学教授。""",
    
    "🏫 神学课堂 (Classroom)": """你是一位严谨的**改革宗神学教授**。
重点评估：
1. **句法逻辑**: 连接词 (For, Therefore) 是否准确。
2. **教义微调**: 严防神学错误 (如 Justify vs Make Righteous)。
风格：冷静、学术、关注逻辑链。""",
    
    "🙏 祷告/灵修 (Devotional)": """你是一位**属灵导师**。
重点评估：
1. **情感深度**: 使用强烈的关系动词 (Pants for vs Miss)。
2. **KJV 亲和力**: 鼓励使用 Thee/Thou。
风格：温柔、敏锐、关注内心。"""
}

def get_coach_instruction(mode):
    """根据模式返回完整的系统指令；mode 必须来自界面下拉框"""
    # 这里假设 mode 已经由界面 selectbox 保证合法，不再强制回退到讲台模式
    mode_instruction = MODE_INSTRUCTIONS[mode]
    return BASE_COACH_INSTRUCTION + "\n\n**MODE-SPECIFIC FOCUS:**\n" + mode_instruction

# 1. 配置与初始化
st.set_page_config(
    page_title="Pulpit Power AI", 
    page_icon="🎙️", 
    layout="centered",  # 移动端友好：居中布局
    initial_sidebar_state="collapsed"  # 默认收起侧边栏
)

# 自定义深色“改革宗神学院”风格主题
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700&family=Roboto:wght@300;400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {
  background-color: #0E1117;
  color: #E0E0E0;
  font-family: 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* 中央学院式内容容器 */
.app-shell {
  max-width: 980px;
  margin: 0 auto;
  padding: 1.25rem 1.5rem 0.5rem 1.5rem;
}

.hero-title {
  font-family: 'Merriweather', 'Georgia', serif;
  font-size: 2.1rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #F8E8C2;
}

.hero-subtitle {
  font-size: 0.9rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(221, 199, 142, 0.9);
  margin-top: 0.25rem;
}

.hero-rule {
  border: none;
  height: 1px;
  margin-top: 0.9rem;
  margin-bottom: 0.4rem;
  background: linear-gradient(90deg, transparent, rgba(212, 175, 55, 0.8), transparent);
}

[data-testid="stSidebar"] {
  background: #11141c;
  border-right: 1px solid rgba(212, 175, 55, 0.25);
}

[data-testid="stSidebar"] h3, [data-testid="stSidebar"] p {
  font-family: 'Merriweather', 'Georgia', serif;
}

h1, h2, h3, h4 {
  font-family: 'Merriweather', 'Georgia', 'Times New Roman', serif;
  color: #F5E6C8;
}

/* 隐藏默认 Header / Footer */
header[data-testid="stHeader"] {
  display: none;
}
footer {
  visibility: hidden;
}

/* 按钮：黑金渐变 */
.stButton > button {
  background: linear-gradient(135deg, #1b1f2a, #D4AF37);
  color: #0E1117;
  border-radius: 999px;
  border: 1px solid #D4AF37;
  padding: 0.5rem 1.25rem;
  font-weight: 600;
  letter-spacing: 0.03em;
}
.stButton > button:hover {
  box-shadow: 0 0 18px rgba(212, 175, 55, 0.45);
  transform: translateY(-1px);
}

/* 输入区：磨砂玻璃效果 */
[data-testid="stFileUploader"], [data-testid="stAudioInput"] {
  background: rgba(18, 22, 33, 0.8);
  border-radius: 12px;
  border: 1px solid rgba(212, 175, 55, 0.35);
  box-shadow: 0 0 25px rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(10px);
}

.stTextInput > div > div > input {
  background-color: rgba(15, 18, 28, 0.9);
  border-radius: 8px;
  border: 1px solid rgba(212, 175, 55, 0.4);
}

/* 题目悬浮卡片 */
.sermon-card {
  background: radial-gradient(circle at top left, rgba(212, 175, 55, 0.18), rgba(9, 11, 17, 0.98));
  border-left: 4px solid #D4AF37;
  border-radius: 14px;
  padding: 1.25rem 1.5rem;
  margin-top: 0.5rem;
  box-shadow: 0 22px 46px rgba(0, 0, 0, 0.85);
}
.sermon-card-ref {
  font-size: 0.85rem;
  letter-spacing: 0.12em;
  color: rgba(244, 231, 186, 0.9);
  text-transform: uppercase;
}
.sermon-card-text {
  font-size: 1.3rem;
  margin-top: 0.4rem;
}

/* 反馈容器 */
.feedback-box {
  border-radius: 14px;
  padding: 1rem 1.15rem;
  margin-top: 0.75rem;
  background: rgba(10, 13, 20, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.feedback-title {
  font-weight: 700;
  margin-bottom: 0.35rem;
}
.feedback-body {
  font-size: 0.95rem;
  line-height: 1.5;
  white-space: pre-wrap;
}
.feedback-pass {
  border-color: #2ecc71;
  box-shadow: 0 0 14px rgba(46, 204, 113, 0.35);
}
.feedback-warning {
  border-color: #f1c40f;
  box-shadow: 0 0 14px rgba(241, 196, 15, 0.3);
}
.feedback-fail {
  border-color: #e74c3c;
  box-shadow: 0 0 18px rgba(231, 76, 60, 0.45);
}

/* 折叠面板 / Tabs 微调 */
[data-testid="stExpander"] {
  border-radius: 12px;
  border: 1px solid rgba(212, 175, 55, 0.4);
  background: rgba(12, 15, 24, 0.95);
}
[data-testid="stTabs"] > div > div {
  background: transparent;
}
[data-baseweb="tab-list"] {
  border-bottom: 1px solid rgba(212, 175, 55, 0.4);
}

.app-footer {
  font-size: 0.8rem;
  color: rgba(224, 224, 224, 0.6);
  text-align: center;
  margin-top: 1.5rem;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# 顶部“神学院”式抬头区域
st.markdown(
    """
    <div class="app-shell">
        <div class="hero-title">AI 神学口译教练</div>
        <div class="hero-subtitle">Reformed Theological Translation Studio</div>
        <hr class="hero-rule" />
    </div>
    """,
    unsafe_allow_html=True,
)

# 后续主体内容也包裹在 app-shell 中，营造居中学院感
st.markdown('<div class="app-shell">', unsafe_allow_html=True)
load_dotenv()

# API 配置 (与工厂一致)
API_KEY = os.getenv("GEMINI_API_KEY")
BASE_URL = os.getenv("GEMINI_BASE_URL", "https://api.laozhang.ai/v1")
MODEL_NAME = "gemini-2.5-flash"

if not API_KEY:
    st.error("❌ 未找到 API Key，请检查 .env 文件")
    st.stop()

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 2. 加载数据函数
@st.cache_data
def load_library():
    data_dir = "assets/bible_data"
    library = {}
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        return library
    
    # 过滤掉 blueprint 文件（这些是给工厂脚本用的，不是给用户的）
    files = [f for f in os.listdir(data_dir) 
             if f.endswith(".json") and not f.startswith("blueprint")]
    for f in files:
        book_name = f.replace(".json", "")
        with open(os.path.join(data_dir, f), "r", encoding="utf-8") as file:
            library[book_name] = json.load(file)
    return library

library = load_library()

# ==================== Helper Functions ====================

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

def generate_audio_sync(text, filename='esv_demo.mp3', voice='en-US-ChristopherNeural', rate='-10%'):
    """Generate audio synchronously using edge_tts and save to cache directory"""
    async def _gen():
        try:
            if not text:
                raise ValueError("Text is empty")
            
            # 清理特殊符号（Markdown格式符号），避免TTS读出这些符号
            clean_text = str(text)
            # 移除 Markdown 格式符号：* _ ` [ ] ( ) # 等
            clean_text = re.sub(r'[*_`\[\]()#]', '', clean_text)
            # 移除多余的空白字符
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            if not clean_text:
                raise ValueError("Text contains no valid characters after cleaning")
            
            # Set locale to UTF-8 to avoid encoding issues
            os.environ['LC_ALL'] = 'C.UTF-8'
            os.environ['LANG'] = 'C.UTF-8'
            
            communicate = edge_tts.Communicate(text=clean_text, voice=voice, rate=rate)
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            
            # Save to cache directory (temp directory)
            cache_dir = os.path.join(tempfile.gettempdir(), "pulpit_power_cache")
            os.makedirs(cache_dir, exist_ok=True)
            output_path = os.path.join(cache_dir, filename)
            with open(output_path, 'wb') as f:
                f.write(audio_data)
            
            return output_path
        except Exception as e:
            # Clean error message
            try:
                clean_error = str(e).encode('utf-8', errors='replace').decode('utf-8')
                error_msg = clean_error
            except:
                error_msg = "Unknown error"
            raise Exception(f"Audio generation failed: {error_msg}")
    
    # Run async function in sync wrapper
    return asyncio.run(_gen())

def generate_chinese_audio_sync(text, filename='chinese_phrase.mp3'):
    """Generate Chinese audio using edge_tts"""
    return generate_audio_sync(text, filename=filename, voice='zh-CN-XiaoxiaoNeural', rate='-5%')

# 4. AI 评估函数（支持音频输入）
def evaluate_translation(audio_data, card, mode):
    """
    评估翻译：使用音频输入，AI 会转录并评分
    mode: 训练模式（讲台/课堂/祷告）
    """
    # 构建用户提示词（包含当前模式及其三大评估重点）
    user_prompt = f"""Here is the audio recording. The user will translate this Chinese phrase to English.

**Context:**
- Reference: {card.get('ref', 'N/A')}
- Chinese phrase: "{card.get('phrase_cn', 'N/A')}"
- Full context: "{card.get('sentence_context', 'N/A')}"
- Expected ESV target: "{card.get('phrase_en', 'N/A')}"
- Key term to focus on: "{card.get('key_term', 'N/A')}"
- Trap to avoid: {card.get('trap', [])}

**Mode & Focus (VERY IMPORTANT):**
- Current mode: {mode}
- Mode-specific focus in Chinese (three bullet points you MUST follow exactly, in order):
{MODE_INSTRUCTIONS[mode]}

**Your task:**
1. Listen to the audio and transcribe EXACTLY what you hear (or "NO_AUDIO" if you hear nothing).
2. **Compare word-by-word:** Your transcription vs ESV target "{card.get('phrase_en', 'N/A')}".
   - Identify missing words, wrong word choices, word order issues.
   - Pay special attention to the KEY TERM: "{card.get('key_term', 'N/A')}".
3. **Evaluate using theological coach rules** from system instruction.
4. **Generate concise feedback:** Compare ESV vs user's speech, explain WHY the difference matters, and HOW to improve. 
   Your feedback MUST be structured into THREE ultra-short lines in Chinese, each line corresponding to ONE bullet point of the current mode:
   - Line 1 = 神学核心 (Theology) → Comment on the FIRST bullet of the current mode.
   - Line 2 = 演绎表现 (Delivery) → Comment on the SECOND bullet of the current mode.
   - Line 3 = 成长聚焦 (Growth) → Comment on the THIRD bullet of the current mode, giving ONE concrete next-step tip.

**CRITICAL: Comparison-Based Feedback**
- Compare: "User said: [transcription]" vs "ESV: {card.get('phrase_en', 'N/A')}"
- Focus on KEY TERM accuracy first, then sentence structure.
- Be BRIEF but PRECISE. Focus on improvement, not just error listing.
- Example: "用 'Establish' 替代 'Make'。这里强调坚立旧约，不是新立。"

**Output JSON format:**
{{
  "status": "pass/warning/fail",
  "user_said": "exact transcription or 'NO_AUDIO'",
  "feedback": "Generate a Markdown-formatted coaching comment in Chinese. Structure it strictly as follows:

**1. 🎯 诊断 (Diagnosis):** Identify the specific gap. Was it a weak verb? A theological drift? Or a lack of rhythm? (Max 1 sentence).

**2. 💡 修正 (Correction):** Provide the specific fix based on the current Mode. 
- If Pulpit Mode: Focus on power ('Use Proclaim!'). 
- If Classroom Mode: Focus on logic ('Add Therefore!'). 
- If Prayer Mode: Focus on emotion ('Use Pant for!').

**3. 🧠 洞见 (Insight):** A brief, memorable 'Theological Rule of Thumb' or 'Mission Field Tip'. (e.g., '神的主权不容被动语态', or '工场上 KJV 的 Thee 更显亲密').

**Style Constraint:** - Professional, authoritative, yet encouraging.
- Total length: Keep it under 150 Chinese characters total.
- Use bolding for key terms."
}}

⚠️ If audio is SILENT/EMPTY: user_said must be "NO_AUDIO" and status must be "fail"
⚠️ user_said MUST be what you actually HEAR, not the expected answer
⚠️ feedback MUST compare ESV vs user_said and provide actionable improvement advice

Output ONLY valid JSON object."""
    
    try:
        if not audio_data:
            return {"status": "fail", "user_said": "NO_AUDIO", "feedback": "未检测到音频输入"}
        
        # 读取音频字节
        audio_bytes = audio_data.read()
        
        if len(audio_bytes) == 0:
            return {"status": "fail", "user_said": "NO_AUDIO", "feedback": "音频文件为空"}
        
        # 根据模式获取系统指令
        coach_instruction = get_coach_instruction(mode)
        
        # 根据 use_proxy 设置创建 client
        if st.session_state.use_proxy:
            # 使用 laozhang.ai 代理
            api_client = OpenAI(
                api_key=API_KEY,
                base_url="https://api.laozhang.ai/v1"
            )
            
            # Convert audio to base64
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            audio_mime_type = get_audio_mime_type(audio_data)
            
            # Call via OpenAI-compatible API with system instruction
            response = api_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": coach_instruction
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
            
            response_text = response.choices[0].message.content
        else:
            # 使用直接 Google API（需要 google.generativeai）
            import google.generativeai as genai
            genai.configure(api_key=API_KEY)
            
            # Try gemini-2.0-flash-exp first, fallback to 1.5-pro, then 2.5-flash
            try:
                model = genai.GenerativeModel('gemini-2.0-flash-exp', system_instruction=coach_instruction)
            except:
                try:
                    model = genai.GenerativeModel('gemini-1.5-pro', system_instruction=coach_instruction)
                except:
                    model = genai.GenerativeModel('gemini-2.5-flash')
            
            # Prepare audio file
            audio_mime_type = get_audio_mime_type(audio_data)
            audio_file = {
                "mime_type": audio_mime_type,
                "data": audio_bytes
            }
            
            # Call Gemini API
            response = model.generate_content([user_prompt, audio_file])
            response_text = response.text
        
        # Parse JSON response
        if not isinstance(response_text, str):
            response_text = str(response_text)
        response_text = response_text.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        response_text = response_text.strip()
        
        result = json.loads(response_text)
        
        # Normalize status
        if 'status' in result:
            result['status'] = result['status'].lower()
        
        return result
        
    except Exception as e:
        # Clean error message
        try:
            error_msg = str(e).encode('utf-8', errors='replace').decode('utf-8')
        except:
            error_msg = "Unknown error"
        return {"status": "fail", "user_said": "ERROR", "feedback": f"AI 连接错误: {error_msg}"}

# 5. 界面布局 (UI)

# --- 初始化 Session State ---
if 'current_index' not in st.session_state:
    st.session_state.current_index = 0
if 'selected_book' not in st.session_state:
    st.session_state.selected_book = None
if 'book_data' not in st.session_state:
    st.session_state.book_data = []
if 'feedback' not in st.session_state:
    st.session_state.feedback = None
if 'use_proxy' not in st.session_state:
    st.session_state.use_proxy = True  # 默认使用 laozhang 中转服务
if 'selected_mode' not in st.session_state:
    st.session_state.selected_mode = list(MODE_INSTRUCTIONS.keys())[0]  # 默认第一个模式

# --- 侧边栏：设置（稳健版）---
with st.sidebar:
    st.markdown("### 🛡️ Pulpit Power")
    
    # 逻辑 1: 基础数据保护
    if not library:
        st.warning("⚠️ 库为空，请检查 assets 路径")
        # 不要在这里用 st.stop()，否则侧边栏就死掉了
        st.info("当前路径: " + os.getcwd()) # 调试用
    else:
        book_options = list(library.keys())
        
        # 逻辑 2: 初始化 Session State (防止 KeyError)
        if 'selected_book' not in st.session_state:
            st.session_state.selected_book = book_options[0]
        if 'current_index' not in st.session_state:
            st.session_state.current_index = 0
            
        # 逻辑 3: 书卷选择器 (去掉复杂的 index 计算，改用简单逻辑)
        # 我们用 on_change 回调来处理重置，而不是在主循环里 rerun
        def on_book_change():
            st.session_state.current_index = 0
            st.session_state.feedback = None
            # 这里的 book_selector 是下面 selectbox 的 key
            st.session_state.selected_book = st.session_state.book_selector

        selected_book = st.selectbox(
            "📚 书卷",
            options=book_options,
            key="book_selector",
            on_change=on_book_change
        )
        
        # 逻辑 4: 确保 book_data 始终有效
        book_data = library.get(st.session_state.selected_book, [])
        
        # 逻辑 5: 模式选择
        mode_options = list(MODE_INSTRUCTIONS.keys())
        selected_mode = st.selectbox(
            "🎯 模式",
            options=mode_options,
            key="selected_mode" # 直接绑定到 session_state
        )
        
        # 进度条
        if book_data:
            st.markdown("---")
            st.caption(f"进度: {st.session_state.current_index + 1} / {len(book_data)}")
            st.progress((st.session_state.current_index + 1) / len(book_data))
# --- 主界面：训练区（移动端优化）---

# --- 1. 数据同步保障 ---
# 检查 book_data 是否为空，或者是否与当前选中的书卷不匹配
if not st.session_state.get('book_data') or st.session_state.get('last_loaded_book') != st.session_state.selected_book:
    # 强制重新从 library 加载
    st.session_state.book_data = library.get(st.session_state.selected_book, [])
    st.session_state.last_loaded_book = st.session_state.selected_book
    st.session_state.current_index = 0  # 确保索引重置

# --- 2. 获取当前题目卡片 (稳健版) ---
book_data = st.session_state.book_data

if book_data and 0 <= st.session_state.current_index < len(book_data):
    current_card = book_data[st.session_state.current_index]
else:
    # 如果还是没有数据，给出一个友好的提示而不是直接 stop
    st.warning(f"⚠️ 正在尝试加载 {st.session_state.selected_book} 的数据...")
    if not library:
        st.error("❌ 严重错误：内存中的 library 为空，请检查文件路径！")
    st.rerun() # 强制刷新一次以同步状态

# 顶部导航栏（学院风导航）
col_title, col_nav = st.columns([3, 1])
with col_title:
    ref_text = current_card.get('ref', 'No Ref')
    st.markdown(f"**{st.session_state.selected_book}** {ref_text}")
with col_nav:
    nav_col1, nav_col2 = st.columns(2)
    with nav_col1:
        if st.session_state.current_index > 0:
            # 使用更内敛的书签式箭头
            if st.button("❮", use_container_width=True, key="prev_btn"):
                st.session_state.current_index -= 1
                st.session_state.feedback = None
                st.rerun()
    with nav_col2:
        if st.session_state.current_index < len(book_data) - 1:
            if st.button("❯", use_container_width=True, key="next_btn"):
                st.session_state.current_index += 1
                st.session_state.feedback = None
                st.rerun()

# 1. 题目卡片：悬浮"讲章卡片"风格（默认不暴露中文原文）
st.markdown(
    f"""
    <div class="sermon-card">
        <div class="sermon-card-ref">{st.session_state.selected_book} · {current_card.get('ref', 'No Ref')}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# 中文音频播放（优先训练"听译"）
try:
    safe_ref = re.sub(r'[^\x20-\x7E]', '_', current_card.get('ref', 'demo'))
    chinese_audio_filename = f"chinese_{safe_ref}.mp3"
    phrase_cn = current_card.get('phrase_cn', '')
    if phrase_cn:
        chinese_audio_file = generate_chinese_audio_sync(phrase_cn, chinese_audio_filename)
        if chinese_audio_file and os.path.exists(chinese_audio_file):
            st.audio(chinese_audio_file, format='audio/mp3')
            st.caption("🎧 中文原文音频")
except Exception as e:
    st.caption("⚠️ 音频生成中...")

# 中文原文折叠显示，优先训练"听译"而非"看译"
phrase_cn = current_card.get('phrase_cn', '暂无中文原文')
if phrase_cn:
    with st.expander("📜 查看中文原文", expanded=False):
        st.markdown(phrase_cn)

# 2. 音频输入区（移动端优化）
st.markdown("---")
tab1, tab2 = st.tabs(["🎙️ 录音", "📁 上传"])

audio_data = None

with tab1:
    audio_data = st.audio_input("点击录音", label_visibility="visible")

with tab2:
    uploaded_file = st.file_uploader(
        "上传音频",
        type=['wav', 'mp3', 'm4a', 'webm', 'ogg']
    )
    if uploaded_file is not None:
        audio_data = uploaded_file
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

# 3. 提交按钮（移动端优化）
st.markdown("---")
if audio_data is not None:
    if st.button("🚀 提交评估", type="primary", use_container_width=True):
        with st.spinner("🤖 AI 分析中..."):
            result = evaluate_translation(audio_data, current_card, st.session_state.selected_mode)
            st.session_state.feedback = result
            st.rerun()
else:
    st.caption("💡 请先录音或上传音频")

# 4. 反馈显示区（自定义学术风格）
if st.session_state.feedback:
    fb = st.session_state.feedback
    status = fb.get('status', 'fail').lower()
    user_said = fb.get('user_said', 'N/A')
    
    st.markdown("---")
    
    # 显示用户实际说的内容
    if user_said and user_said != 'N/A' and user_said.upper() != 'NO_AUDIO':
        with st.container(border=True):
            st.markdown(f"**🎤 您的翻译:** {user_said}")
    
    # 自定义反馈卡片（替代 st.success / st.warning / st.error）
    status_meta = {
        "pass":  {"cls": "feedback-pass",    "title": "✅ 神学评估：通过"},
        "warning": {"cls": "feedback-warning", "title": "🟡 神学评估：需留意"},
        "fail": {"cls": "feedback-fail",    "title": "🔴 神学评估：需重点修正"},
    }
    meta = status_meta.get(status, status_meta["fail"])
    raw_fb = fb.get("feedback", "")
    safe_fb = html.escape(str(raw_fb))
    feedback_html = f"""
    <div class="feedback-box {meta['cls']}">
        <div class="feedback-title">{meta['title']}</div>
        <div class="feedback-body">{safe_fb}</div>
    </div>
    """
    st.markdown(feedback_html, unsafe_allow_html=True)
    
    # 5. 答案揭晓与解析（移动端优化：单列布局）
    with st.expander("🔍 查看解析", expanded=False):
        # 标准发音（顶部）
        try:
            safe_ref = re.sub(r'[^\x20-\x7E]', '_', current_card.get('ref', 'demo'))
            audio_filename = f"esv_demo_{safe_ref}.mp3"
            phrase_en = current_card.get('phrase_en', '')
            if phrase_en:
                generated_file = generate_audio_sync(phrase_en, audio_filename)
                if generated_file and os.path.exists(generated_file):
                    st.audio(generated_file)
                    st.caption("🎧 标准发音")
        except:
            pass
        
        # 目标答案
        phrase_en = current_card.get('phrase_en', '暂无目标答案')
        if phrase_en:
            st.markdown("**🎯 目标答案:**")
            st.info(f"{phrase_en}")
        
        # 完整上下文
        sentence_context = current_card.get('sentence_context', '')
        if sentence_context:
            st.markdown("**📖 完整上下文:**")
            st.caption(f"{sentence_context}")
        
        # 关键词和陷阱
        col_key, col_trap = st.columns(2)
        with col_key:
            key_term = current_card.get('key_term', '')
            if key_term:
                st.markdown("**🔑 关键词:**")
                st.code(key_term, language=None)
        with col_trap:
            trap = current_card.get('trap', [])
            if trap:
                st.markdown("**🪤 陷阱:**")
                if isinstance(trap, list):
                    st.caption(", ".join(trap) if trap else "无")
                else:
                    st.caption(str(trap))
        
        # 解析说明
        nuance_note = current_card.get('nuance_note', '')
        if nuance_note:
            st.markdown("**💡 解析:**")
            st.markdown(f"{nuance_note}")

# 页脚（学院风样式）
st.markdown(
    '<div class="app-footer">Reformed Theological Translation Lab · Powered by Gemini & laozhang.ai</div>',
    unsafe_allow_html=True,
)

# 关闭 app-shell 容器
st.markdown("</div>", unsafe_allow_html=True)