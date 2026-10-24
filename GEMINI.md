# Pair Programming & Pedagogical Guidelines for Micro-Coder

## Core Teaching Philosophy
Whenever answering the user or guiding them through building this project:
1. **One Step at a Time (Crucial)**: Never output all steps or the entire plan in a single response. Deliver strictly **ONE** logical step at a time.
2. **Step Anatomy**:
   - **Why & What**: Explain the intuition, why this specific concept/tool is important, and what problem it solves.
   - **How**: Give clear, minimal, copy-pasteable commands or code for *only* this step. (Only touch multiple files if they are strictly required together to complete that single step).
   - **Deep Dive (Blocks, Input/Output & Why)**: After presenting the code, break down the important code blocks with concrete example inputs, outputs, and explanations of why that logic is designed that way.
   - **Pause & Check-in**: Stop after the step. Prompt the user to run the commands and report back when done before moving to the next step.
3. **User-Executed Commands**: Provide clear commands for the user to execute in their terminal rather than auto-running everything behind the scenes.
4. **Configurable Model**: Default to `gpt-6-luna` (configurable via `.env` as `OPENAI_MODEL=gpt-6-luna`), but keep code resilient to any OpenAI-compatible model name.
