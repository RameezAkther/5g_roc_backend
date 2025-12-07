import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from dotenv import load_dotenv
load_dotenv()

# Make sure GOOGLE_API_KEY is in your env
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",   # or a stable variant
    temperature=0.1,
)

def build_system_prompt(mode: str):
    if mode == "knowledge":
        return (
            "You are a 5G telecom expert assistant. "
            "Use only the given documents and prior messages for answers. "
            "Explain concepts clearly with short, structured answers."
        )
    else:  # analyst
        return (
            "You are a 5G network operations analyst assistant. "
            "You are given recent network metrics and may also see documentation. "
            "Summarize current health and answer questions with data-backed reasoning. "
            "If the data is insufficient, say so."
        )
