import streamlit as st
from perplexity import Perplexity
import json
import toml

# --- 1. CONFIGURATION & INITIALIZATION ---

st.set_page_config(
    page_title="Curiosity Quiz",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- Securely load the API key ---
api_key = None
try:
    # For Streamlit Community Cloud deployment
    api_key = st.secrets["PERPLEXITY_API_KEY"]
except (FileNotFoundError, KeyError):
    # For local development
    try:
        with open("secrets.toml", "r") as f:
            secrets = toml.load(f)
            api_key = secrets.get("PERPLEXITY_API_KEY")
    except FileNotFoundError:
        pass

if not api_key:
    st.error("Perplexity API key not found. Please add it to your Streamlit secrets or a local `secrets.toml` file.")
    st.stop()

client = Perplexity(api_key=api_key)

# --- JSON Schema for consistent API responses ---
quiz_schema = {
    'type': 'object',
    'properties': {
        'question_text': {'type': 'string'},
        'options': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 4, 'maxItems': 4},
        'correct_option_index': {'type': 'integer', 'minimum': 0, 'maximum': 3},
        'explanation': {'type': 'string'},
    },
    'required': ['question_text', 'options', 'correct_option_index', 'explanation'],
}

# --- Initialize Session State ---
if 'game_state' not in st.session_state:
    st.session_state.game_state = 'start'
    st.session_state.topic = ''
    st.session_state.history = []
    st.session_state.current_question = None
    st.session_state.selected_option_index = None
    st.session_state.is_answered = False
    st.session_state.error = None

# --- API Helper Function ---
def get_perplexity_response(messages, model, use_schema=False):
    try:
        params = {"model": model, "messages": messages}
        if use_schema:
            params["response_format"] = {'type': 'json_schema', 'json_schema': {'schema': quiz_schema}}
        
        response = client.chat.completions.create(**params)
        return response.choices[0].message.content
    except Exception as e:
        st.session_state.error = f"API Error: {e}"
        return None

# --- Core Game Logic ---
def start_quiz(topic):
    st.session_state.topic = topic
    st.session_state.history = []
    messages = [
        {'role': 'system', 'content': 'You are an AI quiz master. Always respond in the requested JSON format.'},
        {'role': 'user', 'content': f'Generate the first multiple-choice question for a quiz on "{topic}".'},
    ]
    with st.spinner("Generating first question..."):
        response_content = get_perplexity_response(messages, 'sonar-pro', use_schema=True)
        if response_content:
            st.session_state.current_question = json.loads(response_content)
            st.session_state.game_state = 'quiz'
            reset_turn_state()

def next_question():
    turn_data = {
        **st.session_state.current_question,
        'user_answer': st.session_state.current_question['options'][st.session_state.selected_option_index],
        'is_correct': st.session_state.selected_option_index == st.session_state.current_question['correct_option_index'],
    }
    st.session_state.history.append(turn_data)
    
    if len(st.session_state.history) >= 5: # End quiz after 5 questions
        end_quiz()
        return

    messages = [{'role': 'system', 'content': 'You are an AI quiz master. Always respond in the requested JSON format.'}]
    for turn in st.session_state.history:
        messages.append({'role': 'assistant', 'content': f"Question: {turn['question_text']}"})
        messages.append({'role': 'user', 'content': f"My answer was \"{turn['user_answer']}\". This was {'correct' if turn['is_correct'] else 'incorrect'}."})
    
    messages.append({'role': 'user', 'content': 'Based on our conversation, generate the next logical question.'})

    with st.spinner("Generating next question..."):
        response_content = get_perplexity_response(messages, 'sonar-pro', use_schema=True)
        if response_content:
            st.session_state.current_question = json.loads(response_content)
            reset_turn_state()

def end_quiz():
    st.session_state.game_state = 'summary'
    transcript = "\n".join(
        f"Q: {turn['question_text']}\nYour Answer: {turn['user_answer']} ({'Correct' if turn['is_correct'] else 'Incorrect'})\nCorrect Answer: {turn['options'][turn['correct_option_index']]}\n"
        for turn in st.session_state.history
    )
    messages = [
        {'role': 'system', 'content': "You are an AI learning coach. Analyze the user's quiz performance and provide a detailed, encouraging summary in Markdown."},
        {'role': 'user', 'content': f'The quiz on "{st.session_state.topic}" has ended. Here is the transcript:\n\n{transcript}\n\nProvide a learning analysis with these sections:\n\n### Summary of Topics\n\n### Your Learning Analysis\n\n### What You\'ve Learned'},
    ]
    with st.spinner("Analyzing your results..."):
        summary_content = get_perplexity_response(messages, 'sonar-deep-research')
        if summary_content:
            st.session_state.current_question = {'summary': summary_content}

def restart_game():
    st.session_state.game_state = 'start'
    st.session_state.topic = ''
    st.session_state.history = []
    st.session_state.current_question = None
    reset_turn_state()

def reset_turn_state():
    st.session_state.selected_option_index = None
    st.session_state.is_answered = False
    st.session_state.error = None

# --- UI RENDERING ---

st.title("🧠 Curiosity Quiz")

if st.session_state.error:
    st.error(st.session_state.error)
    if st.button("Start Over"):
        restart_game()
        st.rerun()

elif st.session_state.game_state == 'start':
    st.write("What are you curious about today?")
    with st.form("topic_form"):
        topic_input = st.text_input("Enter a topic", placeholder="e.g., The History of Space Exploration", label_visibility="collapsed")
        submitted = st.form_submit_button("Start Quiz", use_container_width=True, type="primary")
        if submitted and topic_input:
            start_quiz(topic_input)
            st.rerun()

elif st.session_state.game_state == 'quiz' and st.session_state.current_question:
    q = st.session_state.current_question
    question_number = len(st.session_state.history) + 1
    
    st.header(f"Question {question_number} of 5")
    st.markdown(f"#### {q['question_text']}")
    st.divider()

    if not st.session_state.is_answered:
        options = q['options']
        for i, option in enumerate(options):
            if st.button(option, key=f"option_{i}", use_container_width=True):
                st.session_state.selected_option_index = i
                st.session_state.is_answered = True
                st.rerun()
    else:
        for i, option in enumerate(q['options']):
            is_correct = (i == q['correct_option_index'])
            label = f"{'✅' if is_correct else '❌'} {option}"
            st.button(label, disabled=True, key=f"answered_{i}", use_container_width=True)

        if st.session_state.selected_option_index == q['correct_option_index']:
            st.success(f"Correct! {q['explanation']}")
        else:
            st.error(f"Incorrect. {q['explanation']}")
        
        if st.button("Next Question" if question_number < 5 else "Finish Quiz", use_container_width=True, type="primary"):
            next_question()
            st.rerun()

elif st.session_state.game_state == 'summary' and st.session_state.current_question:
    st.header("Quiz Summary")
    st.markdown(st.session_state.current_question['summary'])
    
    col1, col2 = st.columns(2)
    with col1:
        st.button("Dig Deeper (V2)", on_click=lambda: st.toast("This feature is coming soon!"), use_container_width=True)
    with col2:
        st.button("Start a New Quiz", on_click=restart_game, type="primary", use_container_width=True)
