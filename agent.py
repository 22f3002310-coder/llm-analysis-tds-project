from langgraph.graph import StateGraph, END, START
from langchain_core.rate_limiters import InMemoryRateLimiter
from langgraph.prebuilt import ToolNode
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tools import get_rendered_html, download_file, post_request, run_code, add_dependencies, transcribe_audio
from typing import TypedDict, Annotated, List, Any
from langchain.chat_models import init_chat_model
from langgraph.graph.message import add_messages
import os
from dotenv import load_dotenv
load_dotenv()

EMAIL = os.getenv("EMAIL")
SECRET = os.getenv("SECRET")
# -------------------------------------------------
# STATE
# -------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[List, add_messages]


TOOLS = [run_code, get_rendered_html, download_file, post_request, add_dependencies, transcribe_audio]


# -------------------------------------------------
# GEMINI LLM
# -------------------------------------------------
rate_limiter = InMemoryRateLimiter(
    requests_per_second=4/60,  
    check_every_n_seconds=1,  
    max_bucket_size=9  
)
llm = init_chat_model(
   model_provider="google_genai",
   model="gemini-2.5-flash",
   rate_limiter=rate_limiter
).bind_tools(TOOLS)   


# -------------------------------------------------
# SYSTEM PROMPT
# -------------------------------------------------
SYSTEM_PROMPT = f"""
You are an autonomous quiz-solving agent.

Your job is to:
1. Load the quiz page from the given URL.
2. Extract ALL instructions, required parameters, submission rules, and the submit endpoint.
3. Solve the task exactly as required.
4. Submit the answer ONLY to the endpoint specified on the current page (never make up URLs).
5. Read the server response and:
   - If it contains a new quiz URL → fetch it immediately and continue.
   - If no new URL is present → return "END".

STRICT RULES — FOLLOW EXACTLY:

GENERAL RULES:
- NEVER stop early. Continue solving tasks until no new URL is provided.
- NEVER hallucinate URLs, endpoints, fields, values, or JSON structure.
- NEVER shorten or modify URLs. Always submit the full URL.
- NEVER re-submit unless the server explicitly allows or it's within the 3-minute limit.
- ALWAYS inspect the server response before deciding what to do next.
- ALWAYS use the tools provided to fetch, scrape, download, render HTML, or send requests.
- CRITICAL: When submitting an answer, use the URL field from the CURRENT challenge page, not from previous pages.
- When facing an audio task:
  1. Download the audio file.
  2. Use the 'transcribe_audio' tool to get the text.
  3. Extract the answer from the transcription.
- When facing a CSV normalization task:
  1. Download the CSV file.
  2. Parse it carefully, handling inconsistent date formats (e.g., "02/01/24", "2024-01-30", "1 Feb 2024").
  3. Convert ALL dates to ISO-8601 format (YYYY-MM-DD).
  4. Ensure keys are in snake_case.
  5. Convert numeric values to integers (strip whitespace).
  6. Sort by the specified field (usually 'id' ascending).
  7. Return as a JSON array string.
- When facing a GitHub API task:
  1. Download the JSON file with parameters (owner, repo, sha, pathPrefix, extension).
  2. Use get_rendered_html tool to fetch: https://api.github.com/repos/OWNER/REPO/git/trees/SHA?recursive=1
  3. Use run_code tool with Python to parse the JSON and count files. Example code:
     import json; data = json.loads(response_text); 
     count = sum(1 for item in data['tree'] if item['path'].startswith(pathPrefix) and item['path'].endswith(extension))
  4. Calculate offset = (length of your email) mod 2.
  5. Final answer = count + offset. Submit as INTEGER only (not float, not 0.0).
  6. If you cannot solve it within 3 attempts, submit your best guess (like 1) and move to next challenge.

TIME LIMIT RULES:
- Each task has a HARD 3-minute (180 second) limit from when you first fetch the challenge page.
- Track time carefully. If you've spent more than 2.5 minutes on a challenge, submit your best answer immediately.
- The server response includes a "delay" field indicating elapsed time.
- CRITICAL: After EVERY answer submission, check the response for a "url" field.
- If the response contains a "url" field (even if "correct": false), IMMEDIATELY fetch and solve that new URL.
- Only retry the same challenge if the response has NO "url" field AND you're under 3 attempts.
- After 3 attempts on same challenge, if still no "url" in response, return "END".

STOPPING CONDITION:
- Only return "END" when a server response explicitly contains NO new URL after 3 attempts.
- ALWAYS check every response for a "url" field before deciding to retry or stop.
- DO NOT return END if the response contains a "url" field, even if your answer was wrong.

ADDITIONAL INFORMATION YOU MUST INCLUDE WHEN REQUIRED:
- Email: {EMAIL}
- Secret: {SECRET}

YOUR JOB:
- Follow pages exactly.
- Extract data reliably.
- Never guess.
- Submit correct answers.
- Continue until no new URL.
- Then respond with: END
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages")
])

llm_with_prompt = prompt | llm


# -------------------------------------------------
# AGENT NODE
# -------------------------------------------------
def agent_node(state: AgentState):
    result = llm_with_prompt.invoke({"messages": state["messages"]})
    return {"messages": state["messages"] + [result]}


# -------------------------------------------------
# GRAPH
# -------------------------------------------------
def route(state):
    last = state["messages"][-1]
    # support both objects (with attributes) and plain dicts
    tool_calls = None
    if hasattr(last, "tool_calls"):
        tool_calls = getattr(last, "tool_calls", None)
    elif isinstance(last, dict):
        tool_calls = last.get("tool_calls")

    if tool_calls:
        return "tools"
    # get content robustly
    content = None
    if hasattr(last, "content"):
        content = getattr(last, "content", None)
    elif isinstance(last, dict):
        content = last.get("content")

    if isinstance(content, str) and content.strip() == "END":
        return END
    if isinstance(content, list) and content[0].get("text").strip() == "END":
        return END
    return "agent"
graph = StateGraph(AgentState)

graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode(TOOLS))



graph.add_edge(START, "agent")
graph.add_edge("tools", "agent")
graph.add_conditional_edges(
    "agent",    
    route       
)

app = graph.compile()


# -------------------------------------------------
# TEST
# -------------------------------------------------
def run_agent(url: str) -> str:
    app.invoke({
        "messages": [{"role": "user", "content": url}]},
        config={"recursion_limit": 300},
    )
    print("Tasks completed succesfully")

