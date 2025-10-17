import streamlit as st
from perplexity import Perplexity
import json
import toml
import requests # We need this for the advanced summary call

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
    api_key = st.secrets["PERPLEXITY_API_KEY"]
except (FileNotFoundError, KeyError):
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
    st.session_state.summary_content = None
    st.session_state.selected_option_index = None
    st.session_state.is_answered = False
    st.session_state.error = None

# --- API Helper Functions ---
def get_quiz_question(messages):
    """Gets a question using the perplexityai SDK for simplicity."""
    try:
        params = {
            "model": 'sonar-pro',
            "messages": messages,
            "response_format": {'type': 'json_schema', 'json_schema': {'schema': quiz_schema}}
        }
        response = client.chat.completions.create(**params)
        return response.choices[0].message.content
    except Exception as e:
        try:
            error_details = json.loads(e.body)
            st.session_state.error = f"API Error: {error_details['error']['message']}"
        except:
            st.session_state.error = f"An unexpected API error occurred during the quiz: {e}"
        return None

def get_summary_with_sources(messages):
    """
    Gets the summary using a direct `requests` call to add a long timeout and access search_results.
    """
    url = "https://api.perplexity.ai/chat/completions"
    payload = {"model": 'sonar-deep-research', "messages": messages}
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}"
    }
    try:
        # *** THIS IS THE CRITICAL FIX: Adding a long timeout ***
        response = requests.post(url, json=payload, headers=headers, timeout=90)
        response.raise_for_status()
        data = response.json()
        
        summary_text = data['choices'][0]['message']['content']
        search_results = data.get('search_results', [])
        
        if search_results:
            sources_md = "\n\n---\n\n### Sources For Further Learning\n"
            for i, result in enumerate(search_results):
                sources_md += f"{i+1}. [{result.get('title', 'Source Link')}]({result.get('url')})\n"
            summary_text += sources_md
            
        return summary_text
        
    except requests.exceptions.Timeout:
        st.session_state.error = "The request for the summary timed out. The analysis may have been too complex. Please try starting a new, more focused quiz."
    except requests.exceptions.HTTPError as e:
        st.session_state.error = f"API Error during summary: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        st.session_state.error = f"An unexpected error occurred during summary generation: {e}"
    return None

# --- Core Game Logic ---
def start_quiz(topic):
    st.session_state.topic = topic
    st.session_state.history = []
    messages = [
        {'role': 'system', 'content': 'You are an AI quiz master. Always respond in the requested JSON format.'},
        {'role': 'user', 'content': f'Generate the first multiple-choice question for a quiz on "{topic}".'},
    ]
    response_content = get_quiz_question(messages)
    if response_content:
        st.session_state.current_question = json.loads(response_content)
        st.session_state.game_state = 'quiz'
        reset_turn_state()

def next_question():
    turn_data = {
        'question_data': st.session_state.current_question,
        'user_answer': st.session_state.current_question['options'][st.session_state.selected_option_index],
        'is_correct': st.session_state.selected_option_index == st.session_state.current_question['correct_option_index'],
    }
    st.session_state.history.append(turn_data)
    
    if len(st.session_state.history) >= 5:
        st.session_state.game_state = 'summary'
        return

    messages = [{'role': 'system', 'content': 'You are an AI quiz master. Respond in the requested JSON format.'}]
    messages.append({'role': 'user', 'content': f'Let\'s start a quiz on "{st.session_state.topic}".'})
    
    for turn in st.session_state.history:
        messages.append({'role': 'assistant', 'content': json.dumps(turn['question_data'])})
        messages.append({'role': 'user', 'content': f"My answer was \"{turn['user_answer']}\"."})
    
    response_content = get_quiz_question(messages)
    if response_content:
        st.session_state.current_question = json.loads(response_content)
        reset_turn_state()

def generate_summary_and_update_state():
    """Wrapper function to be called from the UI to trigger summary generation."""
    transcript = "\n".join(
        f"Q: {turn['question_data']['question_text']}\n"
        f"Your Answer: {turn['user_answer']} ({'Correct' if turn['is_correct'] else 'Incorrect'})\n"
        f"Correct Answer: {turn['question_data']['options'][turn['question_data']['correct_option_index']]}\n"
        for turn in st.session_state.history
    )
    messages = [
        {'role': 'system', 'content': "You are an AI learning coach. Analyze the user's quiz performance and provide a detailed, encouraging summary in Markdown. Use citations like [1], [2] where relevant."},
        {'role': 'user', 'content': f'The quiz on "{st.session_state.topic}" has ended. Here is the transcript:\n\n{transcript}\n\nProvide a learning analysis with these sections:\n\n### Summary of Topics\n\n### Your Learning Analysis\n\n### Educational Outcome'},
    ]
    summary_content = get_summary_with_sources(messages)
    if summary_content:
        st.session_state.summary_content = summary_content

def restart_game():
    st.session_state.clear()
    st.rerun()

def reset_turn_state():
    st.session_state.selected_option_index = None
    st.session_state.is_answered = False
    st.session_state.error = None

# --- UI RENDERING ---

st.title("🧠 Curiosity Quiz")

if st.session_state.error:
    st.error(st.session_state.error)
    st.button("Start Over", on_click=restart_game, use_container_width=True)

elif st.session_state.game_state == 'start':
    st.write("What are you curious about today?")
    with st.form("topic_form"):
        topic_input = st.text_input("Enter a topic", placeholder="e.g., The Roman Empire", label_visibility="collapsed")
        if st.form_submit_button("Start Quiz", use_container_width=True, type="primary"):
            if topic_input:
                with st.spinner("Generating first question..."):
                    start_quiz(topic_input)
                st.rerun()

elif st.session_state.game_state == 'quiz' and st.session_state.current_question:
    q = st.session_state.current_question
    question_number = len(st.session_state.history) + 1
    
    st.header(f"Question {question_number} of 5")
    st.markdown(f"#### {q['question_text']}")
    st.divider()

    if not st.session_state.is_answered:
        for i, option in enumerate(q['options']):
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
            with st.spinner("Generating next question..."):
                next_question()
            st.rerun()

elif st.session_state.game_state == 'summary':
    if st.session_state.summary_content is None and not st.session_state.error:
        with st.spinner("Analyzing your results and gathering sources..."):
            generate_summary_and_update_state()
    
    if st.session_state.summary_content:
        st.header("Quiz Summary & Educational Outcome")
        st.markdown(st.session_state.summary_content, unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.button("Dig Deeper (V2)", on_click=lambda: st.toast("This feature is coming soon!"), use_container_width=True)
        with col2:
            st.button("Start a New Quiz", type="primary", use_container_width=True, on_click=restart_game)
