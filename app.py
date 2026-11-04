
import os, json, smtplib
from email.mime.text import MIMEText
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 페이지 설정
st.set_page_config(page_title="AI 개인비서 에이블", page_icon="🤖", layout="wide")
st.title("AI 개인비서 에이블")
st.write("김 대리님의 회의록을 분석하고, 음성으로 질문에 답하며 이메일 발송을 도와드립니다.")

# 역할 지정
sys_role = """
당신은 '김 대리'의 개인 AI 비서 '에이블'입니다.
김 대리의 업무를 친절하고 정확하게 지원합니다.
회의록을 받으면 회의 내용과 담당 업무를 요약합니다.
업무의 마감 기한은 명시된 경우에만 안내합니다.
회의록에 없는 내용은 임의로 만들어내지 않습니다.
모든 답변은 한국어로 작성합니다.
이메일 발송 요청이 있을 경우에만 send_email 도구를 사용합니다.
"""

# 이메일 발송 함수 (미션 1, 7)
def send_email(to, subject, body):
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    if not sender or not password:
        return {"status": "failed", "error": "Gmail 설정이 없습니다."}

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, to, msg.as_string())
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

# 도구 정의 (미션 7)
tools = [{
    "type": "function",
    "name": "send_email",
    "description": "사용자가 명시적으로 요청한 경우 이메일을 발송합니다.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "수신자 이메일"},
            "subject": {"type": "string", "description": "이메일 제목"},
            "body": {"type": "string", "description": "이메일 본문"}
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False
    },
    "strict": True
}]

# 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_email" not in st.session_state:
    st.session_state.pending_email = None
if "answer" not in st.session_state:
    st.session_state.answer = ""
if "audio" not in st.session_state:
    st.session_state.audio = None
if "transcript" not in st.session_state:
    st.session_state.transcript = ""

# 답변 저장 및 TTS
def save_answer(answer):
    st.session_state.answer = answer
    st.session_state.messages.append({
        "role": "assistant", "content": answer
    })
    st.session_state.messages = st.session_state.messages[-20:]
    st.session_state.audio = None

    if answer:
        try:
            speech_response = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice="nova",
                input=answer[:3500],
                response_format="mp3"
            )
            st.session_state.audio = speech_response.content
        except Exception as e:
            st.warning(f"음성 변환 오류: {e}")

# 지시 영역
with st.form("task_form"):
    uploaded_file = st.file_uploader("텍스트 파일 업로드", type=["txt"])
    audio_value = st.audio_input("무엇을 도와드릴까요?")
    user_text = st.text_input("또는 텍스트로 질문")
    submit = st.form_submit_button("실행")

# 버튼을 눌렀을 때만 실행
if submit:
    # 업로드된 파일 읽기
    text = ""
    if uploaded_file is not None:
        text = uploaded_file.getvalue().decode("utf-8")

    if audio_value is None and not user_text.strip():
        st.warning("음성을 녹음하거나 질문을 입력해주세요.")
        st.stop()

    # STT: 음성 → 텍스트
    if audio_value is not None:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.wav", audio_value.getvalue(), "audio/wav"),
            language="ko",
            prompt="에이블, 김 대리, 미팅 내용 요약, 담당 업무"
        )
        st.session_state.transcript = transcript.text
        question = transcript.text
    else:
        st.session_state.transcript = ""
        question = user_text.strip()

    # 시스템 메시지
    system_content = sys_role
    if text:
        system_content += f"\n\n다음 내용을 참고하세요:\n{text}"

    # 이전 대화 + 새로운 질문
    input_messages = [
        {"role": "system", "content": system_content}
    ] + st.session_state.messages[-20:] + [
        {"role": "user", "content": question}
    ]

    st.session_state.messages.append({
        "role": "user", "content": question
    })
    st.session_state.messages = st.session_state.messages[-20:]
    st.session_state.pending_email = None

    # LLM 호출
    with st.spinner("답변을 준비하고 있습니다..."):
        response = client.responses.create(
            model="gpt-4o-mini",
            input=input_messages,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=False
        )

        tool_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        if tool_calls and tool_calls[0].name == "send_email":
            call = tool_calls[0]
            st.session_state.pending_email = {
                "args": json.loads(call.arguments),
                "call_id": call.call_id,
                "response_id": response.id
            }
            st.session_state.answer = ""
            st.session_state.audio = None
        else:
            save_answer(response.output_text)

# STT 결과 출력
if st.session_state.transcript:
    st.subheader("음성 인식 결과")
    st.write(st.session_state.transcript)

# 이메일 발송 확인
if st.session_state.pending_email:
    pending = st.session_state.pending_email
    args = pending["args"]

    st.subheader("이메일 발송 확인")
    st.write("수신자:", args["to"])
    st.write("제목:", args["subject"])
    st.text_area("본문", args["body"], height=180, disabled=True)

    if st.button("이메일 발송 승인"):
        result = send_email(args["to"], args["subject"], args["body"])

        final_response = client.responses.create(
            model="gpt-4o-mini",
            previous_response_id=pending["response_id"],
            input=[{
                "type": "function_call_output",
                "call_id": pending["call_id"],
                "output": json.dumps(result, ensure_ascii=False)
            }]
        )

        st.session_state.pending_email = None
        save_answer(final_response.output_text)
        st.rerun()

    if st.button("발송 취소"):
        st.session_state.pending_email = None
        save_answer("이메일 발송을 취소했습니다.")
        st.rerun()

# 응답 확인
if st.session_state.answer:
    st.subheader("AI 답변")
    st.write(st.session_state.answer)

# 음성 듣기
if st.session_state.audio:
    st.audio(st.session_state.audio, format="audio/mp3", autoplay=True)

# 대화 히스토리 관리
with st.expander("최근 대화 기록"):
    for msg in st.session_state.messages[-20:]:
        name = "나" if msg["role"] == "user" else "에이블"
        st.write(f"{name}: {msg['content']}")

    if st.button("대화 기록 초기화"):
        st.session_state.messages = []
        st.session_state.answer = ""
        st.session_state.audio = None
        st.session_state.transcript = ""
        st.rerun()
