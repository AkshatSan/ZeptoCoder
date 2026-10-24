import os
from typing import Generator
from openai import OpenAI
from dotenv import load_dotenv
#1
load_dotenv()
#2
def get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("API key not setup")
    return OpenAI(api_key=api_key)

#3
def stream_chat(
        messages:list[dict],
        model:str | None = None,

) -> Generator[str,None,None]:
    client=get_client()
    chosen_model=model or os.getenv("OPENAI_MODEL", "gpt-6-luna")
    response_stream=client.chat.completions.create(
        model=chosen_model,
        messages=messages,
        stream=True,
    )
    for chunk in response_stream:
        delta=chunk.choices[0].delta
        if delta.content is not None:
            yield delta.content
if __name__ == "__main__":
    import time

    print("Testing stream_chat with model:", os.getenv("OPENAI_MODEL", "gpt-6-luna"))
    test_messages = [{"role": "user", "content": "Say hello in 150 words!"}]
    
    start_time = time.time()
    first_token_time = None
    token_count = 0

    print("Waiting for first token...")
    for token in stream_chat(test_messages):
        current_time = time.time()
        if first_token_time is None:
            first_token_time = current_time
            print(f"\n--> First token arrived after: {first_token_time - start_time:.2f} seconds!\n")
        
        token_count += 1
        # Print each token with elapsed time since the previous token
        print(token, end="", flush=True)

    end_time = time.time()
    generation_duration = end_time - (first_token_time or end_time)
    print(f"\n\nTotal tokens: {token_count}")
    print(f"Time to First Token (Thinking): {first_token_time - start_time:.2f}s")
    print(f"Streaming Duration: {generation_duration:.2f}s")
    if generation_duration > 0:
        print(f"Speed: {token_count / generation_duration:.1f} tokens/second")



