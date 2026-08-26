"""Smallest possible check: can we get one real response from Ollama Cloud?

Run: python 00_connect_test.py
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# Ollama Cloud speaks the OpenAI API, so we reuse ChatOpenAI and just repoint it.
llm = ChatOpenAI(
    model="gpt-oss:120b",
    base_url="https://ollama.com/v1",
    api_key=os.environ["OLLAMA_API_KEY"],
)

resp = llm.invoke("In one sentence, what is an AI agent?")
print("MODEL SAID:\n", resp.content)
print("\nTOKENS USED:", resp.usage_metadata)
