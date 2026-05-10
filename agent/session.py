"""Session persistence: save/restore conversation history to disk.

Sessions are stored as JSON files in .sessions/. Supports resume and fork.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

SESSIONS_DIR = Path(".sessions")
SESSIONS_DIR.mkdir(exist_ok=True)


def create_session() -> Dict[str, Any]:
    """Initialize a fresh session data structure."""
    return {
        "id": uuid.uuid4().hex[:8],
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat(),
        "title": "New Session",
        "messages": [],
    }


def _serialize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Anthropic SDK objects to JSON-serializable dicts."""
    serialized = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            clean = []
            for block in content:
                if hasattr(block, "model_dump"):
                    clean.append(block.model_dump())
                elif hasattr(block, "__dict__"):
                    clean.append(block.__dict__)
                else:
                    clean.append(block)
            content = clean
        serialized.append({"role": msg["role"], "content": content})
    return serialized


def save_session(session: Dict[str, Any]) -> None:
    """Persist session to .sessions/<id>.json."""
    session["updated"] = datetime.now().isoformat()
    file_path = SESSIONS_DIR / f"{session['id']}.json"

    ready = {**session, "messages": _serialize_messages(session["messages"])}
    file_path.write_text(json.dumps(ready, indent=2), encoding="utf-8")


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Load a session from disk by ID prefix."""
    for f in SESSIONS_DIR.glob("*.json"):
        if f.stem.startswith(session_id):
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError) as e:
                print(f"\033[31m  [error] Failed to load session: {e}\033[0m")
                return None
    return None


def list_sessions() -> List[Dict[str, Any]]:
    """Return all saved sessions, most recent first."""
    sessions = []
    files = sorted(
        SESSIONS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for f in files:
        try:
            sessions.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sessions


def print_sessions_table() -> None:
    """Print a formatted table of saved sessions."""
    sessions = list_sessions()
    if not sessions:
        print("  (No saved sessions found)")
        return
    print("\n  \033[4mID        LAST UPDATED         TITLE (MESSAGES)\033[0m")
    for s in sessions:
        mc = len(s.get("messages", []))
        print(
            f"  \033[36m{s['id']}\033[0m  {s['updated'][:19]}  "
            f"{s['title'][:40]:40} \033[90m({mc} msgs)\033[0m"
        )
    print()
