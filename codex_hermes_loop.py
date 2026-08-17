"""
Codex + Hermes Autonomous Self-Healing Code Loop.
- Hermes (Local Ollama 0-Cost): Diagnoses error tracebacks, bug logs, and refactoring needs.
- Codex / Code Engine (Gemini / OpenAI API): Generates exact code edits and replaces buggy code blocks.
- Loop: Executes tests automatically until clean 100% pass status is achieved.
"""
import os
import sys
import time
import subprocess
from dotenv import load_dotenv
from google import genai
from google.genai import types

from hermes_client import is_hermes_available, generate_with_hermes

load_dotenv()

def run_test_command(cmd: str = ".venv/bin/python scratch/test_gemini.py") -> tuple[bool, str]:
    """Execute test command and capture output or error stacktrace."""
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        output = res.stdout + "\n" + res.stderr
        is_success = res.returncode == 0
        return is_success, output.strip()
    except Exception as e:
        return False, str(e)


def diagnose_with_hermes(target_code: str, error_log: str) -> str:
    """Hermes 0-cost local model analyzes error log and creates precise repair blueprint."""
    prompt = f"""다음 파이썬 코드 실행 중 오류가 발생했습니다.
오류 원인을 0원 로컬 에이전트로서 정밀 분석하고, 코드를 어떻게 고쳐야 하는지 상세한 '수정 지침(Fix Blueprint)'을 한국어로 작성하세요.

[오류 코드]
{target_code[:1500]}

[에러 로그 / 스택트레이스]
{error_log[:1500]}

Format:
DIAGNOSIS: (원인 분석 1문장)
FIX_BLUEPRINT: (수정해야 할 구체적 지침)"""

    system_prompt = "You are a senior devops diagnosis agent using Hermes LLM. Create precise bug fix blueprints."
    
    if is_hermes_available():
        out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.1)
        if out:
            print("[Hermes Agent] Local 0-cost diagnosis complete.")
            return out

    return "DIAGNOSIS: Syntax or runtime logic error detected.\nFIX_BLUEPRINT: Resolve the traceback exception in the code."


def mutate_code_with_codex(target_file: str, target_code: str, fix_blueprint: str, api_key: str) -> str:
    """Codex / Code Engine (supports OpenAI API or Gemini Code API) receives Hermes blueprint and auto-rewrites clean corrected code."""
    
    # 1. Check if OpenAI API Key is available for Genuine OpenAI Codex Engine
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            system_msg = "You are the OpenAI Codex Auto-Repair Engine. Output ONLY clean valid code without markdown or explanation."
            user_msg = f"Fix this code based on the Hermes blueprint:\n\n[Blueprint]\n{fix_blueprint}\n\n[Original Code]\n{target_code}"
            
            res = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1
            )
            out = res.choices[0].message.content or ""
            print("[Codex Engine] Successfully regenerated code using genuine OpenAI API (gpt-4o)!")
            return out.replace("```python", "").replace("```", "").strip()
        except Exception as e:
            print(f"[OpenAI Codex Warning] {e}, falling back to Gemini Code Engine...")

    # 2. Fallback to Gemini Code Engine
    client = genai.Client(api_key=api_key)
    prompt = f"""You are the Codex Auto-Repair Code Engine.
Modify the following Python code based strictly on the Hermes Diagnosis Blueprint.

[Hermes Fix Blueprint]
{fix_blueprint}

[Original Code]
{target_code}

CRITICAL RULES:
- Output ONLY the complete, corrected valid Python code.
- Do NOT wrap code in markdown backticks (```python ... ```) or add any conversational intro text.
- Ensure 100% syntactically correct code."""

    res = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=2000)
    )
    
    clean_code = res.text or ""
    return clean_code.replace("```python", "").replace("```", "").strip()


def run_codex_hermes_self_healing_loop(target_file: str, test_cmd: str, api_key: str | None = None, max_iterations: int = 3) -> bool:
    """Run Codex + Hermes Self-Healing Loop until test passes or max iterations reached."""
    effective_api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not effective_api_key:
        print("[Self-Healing Loop Warning] API Key not provided. Hermes diagnosis can run, but Codex code mutation requires API key.")

    print(f"🚀 Starting Codex + Hermes Self-Healing Loop for target file: {target_file}")
    
    for i in range(1, max_iterations + 1):
        print(f"\n--- Iteration {i}/{max_iterations} ---")
        success, log = run_test_command(test_cmd)
        
        if success:
            print("🎉 [Self-Healing Loop] Test Passed 100%! Code is clean and error-free.")
            return True
            
        print(f"❌ Test Failed. Error detected in log.\n[Log Preview]: {log[:200]}...")
        
        # Read target code
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            code_content = f.read()
            
        # Step 1: Hermes Diagnosis (0-Cost Local Agent)
        print("🤖 Step 1: Hermes Local Agent analyzing error log (0-Cost)...")
        blueprint = diagnose_with_hermes(code_content, log)
        print(f"   ↳ Hermes Fix Blueprint:\n{blueprint}")
        
        # Save blueprint to scratch/fix_blueprint.txt for user inspection
        blueprint_file_path = os.path.join(os.path.dirname(__file__), "scratch", "fix_blueprint.txt")
        os.makedirs(os.path.dirname(blueprint_file_path), exist_ok=True)
        with open(blueprint_file_path, "w", encoding="utf-8") as bf:
            bf.write(f"=== Hermes Auto Fix Blueprint (Iteration {i}) ===\n\n{blueprint}\n")
        print(f"   💾 Saved Fix Blueprint to: {blueprint_file_path}")
        
        # Step 2: Codex Code Mutation
        if effective_api_key:
            print("⚡ Step 2: Codex Engine rewriting fixed code...")
            repaired_code = mutate_code_with_codex(target_file, code_content, blueprint, effective_api_key)
            
            if repaired_code and len(repaired_code) > 20:
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(repaired_code)
                print(f"   ↳ Clean repaired code written to {target_file}")
        else:
            print("⚠️ Skipped Step 2 (Codex Mutation) because API key is missing.")
            break
            
        time.sleep(1)
        
    return False


if __name__ == "__main__":
    print("Testing Codex + Hermes Loop module initialization...")
